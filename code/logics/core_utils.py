from typing import List, Dict, Optional, Type, Union, BinaryIO, Tuple
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
import pandas as pd
import logging
from calendar import month_name
import os
import re
from pandas._typing import AstypeArg
import json

from code.settings import BASE_DIR
from code.logics.db import (
    DBManager, 
    RosterModel, 
    SkillingModel,
    ProdTeamRosterModel,
    InValidSearchException, 
    RosterTemplate, 
    ForecastModel, 
    ForecastMonthsModel
)
import warnings
# warnings.filterwarnings("ignore")
from code.settings import  (
    MODE,
    SQLITE_DATABASE_URL, 
    MSSQL_DATABASE_URL,
    BASE_DIR
)


if MODE.upper() == "DEBUG":
    DATABASE_URL = SQLITE_DATABASE_URL
elif MODE.upper() == "PRODUCTION":
    DATABASE_URL = MSSQL_DATABASE_URL
else:
    raise ValueError("Invalid MODE specified in config.")


logger = logging.getLogger(__name__)


class CoreUtils:
    def __init__(self, database_url: str):
        self.db_url = database_url

    def get_db_manager(
        self,
        Model,
        limit: int = 0,
        skip: int = 0,
        select_columns: Optional[List[str]] = None
    ) -> DBManager:
        return DBManager(self.db_url, Model, limit, skip, select_columns)

def get_model_or_all_models(file_id:str=None)-> Union[Dict[str, Type], Type]:
    """
    Retrieve a model class by its identifier or return all model mappings.

    Args:
        file_id (str, optional): The identifier for the model. Use 'All' to get all mappings.

    Returns:
        Union[Dict[str, Type], Type]: The model class or the mapping dictionary.

    Raises:
        HTTPException: If the model is not found.
    """

    if file_id is None:
        raise HTTPException(status_code=400, detail="file_id must be provided")
    
    # Define the mapping of models and params
    MODEL_FIELD_MAPPING: Dict[str, Union[Type, Dict[str, Type]]] = {
        'roster': RosterModel,
        'skilling': SkillingModel,  
        'roster_template': RosterTemplate,
        'forecast': ForecastModel,
        'upload_roster': {
            'Roster': RosterModel,
            'Skilling': SkillingModel
        },
        'prod_team_roster': ProdTeamRosterModel,   
    }
    ALL_MODELS_KEY = 'All'

    if file_id.lower() == ALL_MODELS_KEY.lower():
        return {key: value for key, value in MODEL_FIELD_MAPPING.items() if key != 'upload_roster'}
    
    model = MODEL_FIELD_MAPPING.get(file_id.lower())
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    
    return model

def _safe_filename(text: str) -> str:
    """Trim at first asterisk and strip characters invalid for filenames."""
    text = re.match(r'^[^*]*', str(text)).group(0) if text else ""
    return re.sub(r'[\/:*?"<>|]', '', text).strip()

def convert_to_month(x):
    try:
        return pd.to_datetime(x).strftime('%B')
    except Exception:
        return x

def generate_consecutive_months(start_month: str, count: int = 6) -> List[str]:
    """
    Generate a list of consecutive month names starting from start_month.
    Handles year wraparound automatically.

    Args:
        start_month: Starting month name (e.g., "November", "January")
        count: Number of consecutive months to generate (default: 6)

    Returns:
        List of month names in consecutive order

    Examples:
        >>> generate_consecutive_months("January", 6)
        ['January', 'February', 'March', 'April', 'May', 'June']

        >>> generate_consecutive_months("November", 6)
        ['November', 'December', 'January', 'February', 'March', 'April']

    Raises:
        ValueError: If start_month is not a valid month name
    """
    months = list(month_name)[1:]  # ['January', 'February', ..., 'December']

    # Validate start_month
    if start_month not in months:
        raise ValueError(f"Invalid month name: {start_month}")

    # Find starting index
    start_idx = months.index(start_month)

    # Generate consecutive months with wraparound
    result = []
    for i in range(count):
        result.append(months[(start_idx + i) % 12])

    return result

def get_columns_between_column_names(
    df: pd.DataFrame,
    col_level: int = 0,
    start_col_name: str = None,
    end_col_name: str = None
) -> List[str]:
    """
    Returns a list of column names (from the specified row of columns) between start_col_name and the first end_col_name, without duplicates.
    Edge cases:
      - If both start_col_name and end_col_name are missing, returns all columns.
      - If only start_col_name is present, returns columns from that name to the end.
      - If only end_col_name is present, returns columns from start up to (not including) that name.
      - If both are present, returns columns between them.
    """
    if df is None or df.empty or not hasattr(df, "columns"):
        return []

    first_row = df.columns.get_level_values(col_level)
    first_row_str = [str(col).strip() for col in first_row]
    first_row_lower = [col.lower() for col in first_row_str]

    start_idx = None
    end_idx = None

    if start_col_name:
        start_col_name_lower = str(start_col_name).strip().lower()
        if start_col_name_lower in first_row_lower:
            start_idx = first_row_lower.index(start_col_name_lower)
    if end_col_name:
        end_col_name_lower = str(end_col_name).strip().lower()
        # Find first occurrence of end_col_name after start_idx
        search_start = (start_idx + 1) if start_idx is not None else 0
        try:
            end_idx = first_row_lower.index(end_col_name_lower, search_start)
        except ValueError:
            end_idx = None

    # Logic for edge cases
    if start_idx is not None and end_idx is not None and end_idx > start_idx:
        cols = first_row_str[start_idx + 1:end_idx]
    elif start_idx is not None:
        cols = first_row_str[start_idx + 1:]
    elif end_idx is not None:
        cols = first_row_str[:end_idx]
    else:
        cols = first_row_str

    # Remove duplicates while preserving order
    seen = set()
    unique_cols = [x for x in cols if x and not (x in seen or seen.add(x))]
    return unique_cols

def clean_series(
    s: pd.Series,
    *,
    min_numeric_ratio: float = 0.8,   # only convert text columns if >=80% numeric
    fill_empty_numeric: float = 0.0,  # default fill for numeric empties
    fill_empty_string: str = ""       # default fill for string empties
) -> pd.Series:
    # Case 0: column is entirely missing (NaN)
    if s.isna().all():
        if pd.api.types.is_numeric_dtype(s.dtype):
            # keep it numeric (float) so rounding works
            return pd.Series(fill_empty_numeric, index=s.index, dtype="float64").round(2)
        else:
            # preserve as string column
            return pd.Series(fill_empty_string, index=s.index, dtype="string")

    # If it's already numeric, clean as numeric
    if pd.api.types.is_numeric_dtype(s.dtype):
        s_num = pd.to_numeric(s, errors="coerce")
        # float if any fractional part; otherwise nullable int
        has_fraction = (s_num.dropna() % 1 != 0).any()
        if has_fraction or pd.api.types.is_float_dtype(s.dtype):
            return s_num.fillna(fill_empty_numeric).round(2)
        else:
            return s_num.fillna(0).astype("Int64")

    # Non-numeric dtype: decide whether it should become numeric
    s_num = pd.to_numeric(s, errors="coerce")
    numeric_ratio = s_num.notna().mean()

    if numeric_ratio >= min_numeric_ratio:
        # Treat as numeric
        has_fraction = (s_num.dropna() % 1 != 0).any()
        if has_fraction:
            return s_num.fillna(fill_empty_numeric).round(2)
        else:
            return s_num.fillna(0).astype("Int64")
    else:
        # Keep as strings and fill missing with empty string (or your choice)
        return s.fillna(fill_empty_string).astype("string")

def clean_multiindex_df(df_multi: pd.DataFrame) -> pd.DataFrame:
    # Drop columns where header row index 3 contains '.1' or '.2'
    # if df_multi.empty:
    #     return df_multi
    df_multi = df_multi.loc[:, ~df_multi.columns.duplicated()] 
    cols_to_drop = [col for col in df_multi.columns if any(str(col[3]) == suffix for suffix in ('.1', '.2'))]
    df_multi = df_multi.drop(columns=cols_to_drop, axis=0)
    try:
        # Process each column for type and fill NaNs
        for j in range(df_multi.shape[1]):
            df_multi.iloc[:, j] = clean_series(df_multi.iloc[:, j])
    except Exception as e:
        logger.error(f"Error occured while cleaning summary data: {e}")
    return df_multi

def extract_summary_tables(filestream) -> dict[str, pd.DataFrame]:
    """
    Extracts tables from the 'Forecast v Capacity Summary' sheet of the given Excel file stream.
    Returns a dictionary: {safe_filename: dataframe}, skipping keys containing 'MMP' or 'Combined'.
    """
    forecast_excel_df = pd.read_excel(filestream, sheet_name='Forecast v Capacity Summary', dtype=str, header=None)
    start_index = 0
    max_rows = len(forecast_excel_df)
    empty_row_count = 0
    client_names = ['amisys', 'xcelys', 'OIC', 'facets']
    tables_dict = {}


    while start_index < max_rows:
        found_start = False
        for idx in range(start_index, max_rows):
            if forecast_excel_df.iloc[idx].astype(str).str.contains("|".join(client_names), case=False, na=False, regex=True).any():
                start_index = idx
                found_start = True
                empty_row_count = 0
                header_value = forecast_excel_df.iloc[start_index].dropna().iloc[0]
                safe_filename = _safe_filename(header_value)
                # re.sub(r'[\/:*?"<>|]', '', trim_at_asterisk(str(header_value)))
                break
            elif forecast_excel_df.iloc[idx].isna().all():
                empty_row_count += 1
                if empty_row_count >= 3:
                    return tables_dict
            else:
                empty_row_count = 0

        if not found_start:
            break

        end_index = start_index + 1
        while end_index < max_rows:
            if forecast_excel_df.iloc[end_index].astype(str).str.contains("Total", case=False, na=False).any():
                if (end_index + 1 < max_rows and forecast_excel_df.iloc[end_index + 1].isna().all()):
                    # if (end_index + 2 < max_rows and forecast_excel_df.iloc[end_index + 2].isna().all()):
                    #     end_index += 1
                    #     start_index = end_index + 1
                    break
            end_index += 1

        if end_index >= max_rows - 1:
            end_index = max_rows - 1

        if "OIC" in safe_filename:
            print(f"filename: {safe_filename} start index -> {start_index} and End index -> {end_index}")

        table_df = forecast_excel_df.iloc[start_index:end_index + 1]
        table_df = table_df.dropna(axis=1, how='all')
        if "OIC" in safe_filename:
            print(table_df.head())
        table_df = table_df[~table_df.astype(str).apply(lambda row: row.str.startswith("YYYY", na=False)).any(axis=1)]

        if "OIC" in safe_filename:
            print(table_df.head())
        # Skip storing if safe_filename contains 'MMP' or 'Combined'
        if any(x in safe_filename.upper() for x in ["MMP", "COMBINED"]):
            start_index = end_index + 2
            continue
        
        # Try to read as multi-index header if possible
        try:
            from io import BytesIO
            buffer = BytesIO()
            table_df.to_excel(buffer, index=False)
            buffer.seek(0)
            df_multi = pd.read_excel(buffer, header=[1, 2, 3, 4])
            df_multi.columns = df_multi.columns.map(lambda x: tuple(i if 'Unnamed' not in str(i) else '' for i in x))
            df_multi.columns = pd.MultiIndex.from_tuples(
                tuple(
                    convert_to_month(col[2]) if i == 2 else col[i]
                    for i in range(len(col))
                )
                for col in df_multi.columns
            )
            df_multi.reset_index(drop=True, inplace=True)
            df_multi = clean_multiindex_df(df_multi)
            tables_dict[safe_filename] = df_multi
        except Exception:
            table_df.reset_index(drop=True, inplace=True)
            tables_dict[safe_filename] = table_df

        start_index = end_index + 2

    return tables_dict

class PreProcessing:
    def __init__(self, file_id, ):
        self.file_id = file_id
        self.month_codes = {}
        self.abbr_to_full = {
            'Jan': 'January', 'Feb': 'February', 'Mar': 'March', 'Apr': 'April',
            'May': 'May', 'Jun': 'June', 'Jul': 'July', 'Aug': 'August',
            'Sep': 'September', 'Sept': 'September', 'Oct': 'October',
            'Nov': 'November', 'Dec': 'December'
        }
        self.MAPPING = {
            'roster': [
                        'Platform', 'WorkType', 'State', 'Product', 'Location',
                        'ResourceStatus', 'Status', 'FirstName', 'LastName', 'PortalId', 'CN',
                        'WorkdayId', 'HireDate_AmisysStartDate', 'OPID', 'Position', 'TL',
                        'Supervisor', 'PrimarySkills', 'SecondarySkills', 'City', 'ClassName',
                        'FTC_START_TRAINING', 'FTC_END_TRAINING', 'ADJ_COB_START_TRAINING',
                        'ADJ_COB_END_TRAINING', 'CourseType', 'BH', 'SplProj', 'DualPends',
                        'RampStartDate', 'RampEndDate', 'Ramp', 'CPH',
                        'CrossTrainedTrainingDate', 'CrossTrainedProdDate',
                        'ProductionStartDate', 'Facilitator_Cofacilitator',                
                        'Centene_WellCareEmail', 'Additional_Email_NTT'
                        ],
            'roster_template':[
                        'FirstName', 'LastName', 'CN', 'OPID', 'Location', 'ZIPCode', 'City', 
                        'BeelineTitle', 'Status', 'PrimaryPlatform', 'PrimaryMarket', 'Worktype', 
                        'LOB', 'SupervisorFullName', 'SupervisorCNNo', 'UserStatus', 'PartofProduction', 
                        'ProductionPercentage', 'NewWorkType', 'State', 'CenteneMailId', 'NTTMailID'
                        ],
            'forecast':[
                    'Centene_Capacity_Plan_Main_LOB', 'Centene_Capacity_Plan_State', 'Centene_Capacity_Plan_Case_Type', 
                    'Centene_Capacity_Plan_Call_Type_ID', 'Centene_Capacity_Plan_Target_CPH', 
                    'Client_Forecast_Month1', 'Client_Forecast_Month2', 'Client_Forecast_Month3', 'Client_Forecast_Month4', 
                    'Client_Forecast_Month5', 'Client_Forecast_Month6', 'FTE_Required_Month1', 'FTE_Required_Month2', 'FTE_Required_Month3', 
                    'FTE_Required_Month4', 'FTE_Required_Month5', 'FTE_Required_Month6', 'FTE_Avail_Month1', 'FTE_Avail_Month2', 'FTE_Avail_Month3', 
                    'FTE_Avail_Month4', 'FTE_Avail_Month5', 'FTE_Avail_Month6', 'Capacity_Month1', 'Capacity_Month2', 'Capacity_Month3', 'Capacity_Month4', 
                    'Capacity_Month5', 'Capacity_Month6'
            ],
            'skilling':[
                "Position", "FirstName", "LastName", "PortalId", "Status", "Resource_Status",
                "LOB_1", "Sub_LOB", "Site", "Skills", "State", "Unique_Agent",
                "Multi_Skill", "Skill_Name", "Skill_Split"
            ],
            'prod_team_roster' : [
                "FirstName", "LastName", "CN", "OPID", "Location", "ZIPCode", "City",
                "BeelineTitle", "Status",
                "PrimaryPlatform", "PrimaryMarket", "Worktype",
                "LOB", "SupervisorFullName", "SupervisorCNNo",
                "UserStatus", "PartofProduction", "ProductionPercentage",
                "NewWorkType", "State", "CenteneMailId", "NTTMailID"
            ]

        }
        self.model_keys = {
            'forecast': [
                'Centene_Capacity_Plan_Main_LOB', 'Centene_Capacity_Plan_State', 
                'Centene_Capacity_Plan_Case_Type', 'Centene_Capacity_Plan_Call_Type_ID',
            ],
        }

    
    def _normalize_month(self, month_str):
        month_str = month_str.strip().capitalize()
        # Handle abbreviations
        if month_str.isdigit():
            month_num = int(month_str)
            return month_name[month_num]
        elif month_str in self.abbr_to_full:
            return self.abbr_to_full[month_str]
        else:
            return month_str  # Already full name

    def get_month_year(self,filename):
        # List of month names and abbreviations
        
        months = [item for pair in self.abbr_to_full.items() for item in pair]
        # Build a regex pattern for months
        month_pattern = '|'.join(months)
        # Pattern to match: month (word or number), optional separator, year (4 digits)
        pattern = rf'({month_pattern}|\b[0]?[1-9]|1[0-2]\b)[\s\-_]+(\d{{4}})'

        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            month = self._normalize_month(match.group(1))
            year = match.group(2)
            return {"Month": month, "Year": year}
        else:
            return None
    
    def _process_forecast_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Processes the forecast DataFrame to ensure it has the correct columns and formats"""
        # Get the second level of the MultiIndex columns
        second_level = df.columns.get_level_values(1)
        # Extract unique months in the order they appear in 'months'
        unique_months = [m for m in self.abbr_to_full.values() if m in set(second_level)]
        self.month_codes = {f"Month{i+1}":month  for i, month in enumerate(unique_months)}


        # df = pd.read_excel(path, header=list(range(header_rows)))
        # Flatten the MultiIndex columns
        df.columns = [
            "_".join([str(i) for i in col if str(i) != 'nan']).strip("_")
            for col in df.columns.values
        ]

        return df
        


    def _process_forecast(self, contents:bytes|str, header_rows:int=2):
        """
        Reads an Excel file with multi-level headers and flattens the header.

        Args:
            content (bytes): Excel file as bytes. contents:bytes
            header_rows (int): Number of header rows to read (default 2).
            
        Returns:
            pd.DataFrame: DataFrame with flattened column headers.
        """
        # Read the Excel file with multi-level headers
        df = pd.read_excel(contents, header=list(range(header_rows)))
        
        df = self._process_forecast_df(df)
        
        return df
    
    def preprocess_file(self,contents:bytes|str):
        columns = self.MAPPING[self.file_id]
        if self.file_id in ['roster', 'roster_template', 'prod_team_roster']:
            
            df = pd.read_excel(contents, names=columns)
        if self.file_id in ['forecast']:
            df = self._process_forecast(contents)
            df.columns = columns

        return df
    
    def preprocess_forecast_df(self, df:pd.DataFrame) -> pd.DataFrame:
        columns = self.MAPPING[self.file_id]
        df = self._process_forecast_df(df)
        df.columns = columns
        return df

    def preprocess_roster(self, df: pd.DataFrame) -> pd.DataFrame:
        expected = self.MAPPING["roster"]
        df.columns = df.columns.str.strip()
        df = df[expected] if all(col in df.columns for col in expected) else pd.read_excel(df, names=expected)
        for col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
        return df

    def preprocess_skilling(self, df: pd.DataFrame) -> pd.DataFrame:
        df.columns = self.MAPPING["skilling"]
        df.columns = df.columns.str.strip()
        int_cols = ['Unique_Agent', 'Multi_Skill']
        float_cols = ['Skill_Split']

        for col in df.columns:
            if col in int_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            elif col in float_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0).astype(float)
            else:               
                df[col] = df[col].fillna("").astype(str).str.strip()
        return df
    
    def get_model_keys(self):
        return self.model_keys.get(self.file_id,[])

    @staticmethod
    def _read_multi_sheet(
        file_stream: Union[str, BinaryIO],
        sheet: str,
        *,
        header_depth: int = 3,
        skiprows: int = 1,
        skipfooter: int = 0,
    ) -> pd.DataFrame:
        """Read an Excel sheet with a multi-row header and normalize 'Unnamed'."""
        headers = list(range(0, header_depth))
        df = pd.read_excel(
            file_stream, sheet_name=sheet, header=headers, dtype=str,
            skiprows=skiprows, skipfooter=skipfooter
        )
        df.columns = pd.MultiIndex.from_tuples(
            tuple("" if "Unnamed" in str(lvl) else lvl for lvl in tup)
            for tup in df.columns
        )
        return df

    def process_forecast_file(
        self,
        file_stream: Union[str, BinaryIO],
        *,
        non_mmp_domestic_sheet: str = "Amisys Medicaid DOMESTIC",
        non_mmp_global_sheet: str = "Amisys Medicaid GLOBAL",
        mmp_sheet: str = "Amisys MMP State Level",
        domestic_states: Tuple[str, ...] = ("MI", "OH", "TX"),
        global_states: Tuple[str, ...] = ("IL", "SC"),
    ) -> Dict[str, Dict[str, pd.DataFrame]]:

        """
        Processes the forecast Excel file and extracts relevant sheets into cleaned DataFrames.

        Args:
            file_stream: File-like object or path to Excel file.

        Returns:
            dict: {
            "medicare_medicaid_nonmmp": {
                "Amisys Medicaid DOMESTIC": DataFrame,
                "Amisys Medicaid GLOBAL": DataFrame
            },
            "medicare_medicaid_mmp": {
                "AMISYS MMP Domestic": DataFrame,
                "AMISYS MMP Global": DataFrame
            },
            "medicare_medicaid_summary": dict[str, DataFrame]
        }
        Raises:
            ValueError: If any required sheet is missing.
        """
        # Check for required sheets
        required_sheets = [
            non_mmp_domestic_sheet,
            non_mmp_global_sheet,
            mmp_sheet,
            "Forecast v Capacity Summary"
        ]
        # Get sheet names
        xl = pd.ExcelFile(file_stream)
        missing = [sheet for sheet in required_sheets if sheet not in xl.sheet_names]
        if missing:
            raise ValueError(f"Missing required sheet(s): {', '.join(missing)}")

        dfs = {}
        non_mmp = {}

        non_mmp[non_mmp_domestic_sheet] = self._read_multi_sheet(
            file_stream, non_mmp_domestic_sheet, header_depth=3, skiprows=1
        )
        non_mmp[non_mmp_global_sheet] = self._read_multi_sheet(
            file_stream, non_mmp_global_sheet, header_depth=3, skiprows=1
        )
        dfs["medicare_medicaid_nonmmp"] = non_mmp

        mmp_df = self._read_multi_sheet(
            file_stream, mmp_sheet, header_depth=2, skiprows=1, skipfooter=1
        )
        # mmp_df = mmp_df.sort_index(axis=1)
        state_col = mmp_df.get(("State", "State"))
        if state_col is None:
            raise KeyError("Expected ('State','State') column not found in MMP sheet.")

        state_series = state_col if isinstance(state_col, pd.Series) else state_col.iloc[:, 0]

        domestic_mask = state_series.isin(domestic_states)
        global_mask = state_series.isin(global_states)

        mmp_parts = {
            "AMISYS MMP Domestic": mmp_df.loc[domestic_mask].reset_index(drop=True),
            "AMISYS MMP Global": mmp_df.loc[global_mask].reset_index(drop=True),
        }
        dfs["medicare_medicaid_mmp"] = mmp_parts

        dfs["medicare_medicaid_summary"] = extract_summary_tables(file_stream)
        unique_months = []
        for _, df in dfs["medicare_medicaid_summary"].items():
            if not df.empty:
                if df.columns.nlevels == 4:
                    unique_months = get_columns_between_column_names(df, 2, 'CPH', 'Work Type')
                    break

        # Error if no months found
        if not unique_months or len(unique_months) == 0:
            raise ValueError("No forecast months found in summary file")

        # Generate exactly 6 consecutive months from first month found
        first_month = unique_months[0]
        consecutive_months = generate_consecutive_months(first_month, 6)
        month_codes = {f"Month{i+1}": month for i, month in enumerate(consecutive_months)}

        self.month_codes = month_codes
        return dfs


   
def insert_file_id(db_manager:DBManager, file_id):
    result = db_manager.read_db()
    output = {'total':result['total'], 'records':[]}
    for r in result['records']:
        row = r
        row['FileType'] = file_id
        output['records'].append(row)

    return output



class PostProcessing:
    def __init__(self, core_utils: CoreUtils):      
        self.core_utils = core_utils
        
        self.MAPPING = {
            'forecast':[
                ('Centene Capacity plan', 'Main LOB'),
                ('Centene Capacity plan', 'State'),
                ('Centene Capacity plan', 'Case type'),
                ('Centene Capacity plan', 'Call Type ID'),
                ('Centene Capacity plan', 'Target CPH'),
                ('Client Forecast', 'Month1'),
                ('Client Forecast', 'Month2'),
                ('Client Forecast', 'Month3'),
                ('Client Forecast', 'Month4'),
                ('Client Forecast', 'Month5'),
                ('Client Forecast', 'Month6'),
                ('FTE Required', 'Month1'),
                ('FTE Required', 'Month2'),
                ('FTE Required', 'Month3'),
                ('FTE Required', 'Month4'),
                ('FTE Required', 'Month5'),
                ('FTE Required', 'Month6'),
                ('FTE Avail', 'Month1'),
                ('FTE Avail', 'Month2'),
                ('FTE Avail', 'Month3'),
                ('FTE Avail', 'Month4'),
                ('FTE Avail', 'Month5'),
                ('FTE Avail', 'Month6'),
                ('Capacity', 'Month1'),
                ('Capacity', 'Month2'),
                ('Capacity', 'Month3'),
                ('Capacity', 'Month4'),
                ('Capacity', 'Month5'),
                ('Capacity', 'Month6'),
            ],
            'roster':[
                        'Platform', 'WorkType', 'State', 
                        'Product', 'Location', 'ResourceStatus', 
                        'Status', 'FirstName', 'LastName', 'PortalId', 
                        'CN', 'WorkdayId', 'HireDate_AmisysStartDate', 
                        'OPID', 'Position', 'TL', 'Supervisor', 'PrimarySkills', 
                        'SecondarySkills', 'City', 'ClassName', 'FTC_START_TRAINING', 
                        'FTC_END_TRAINING ', 'ADJ_COB_START_TRAINING', 'ADJ_COB_END_TRAINING ', 
                        'CourseType', 'BH', 'SplProj', 'DualPends', 'RampStartDate', 'RampEndDate', 
                        'Ramp', 'CPH', 'CrossTrainedTrainingDate', 'CrossTrainedProdDate', 'ProductionStartDate', 
                        'Facilitator_Cofacilitator', ' Centene_WellCareEmail', 'Additional_Email_NTT'
                    ],
            'roster_template':[
                                'FirstName', 'LastName', 'CN', 'OPID', 'Location', 'ZIPCode', 'City', 'BeelineTitle', 
                             'Status\n[inTrainingorProduction]', 'PrimaryPlatform', 'PrimaryMarket', 'Worktype(FTC/ADJ/COB)', 
                             'LOB', "Supervisor'sFullName", "Supervisor'sCN#", 'UserStatus', 'PartofProduction', 'Production%', 
                             'NewWorkType', 'State', 'CenteneMailId', 'NTTMailID'
                             ],
            'skilling':[
                "Position", "FirstName", "LastName", "PortalId", "Status", "Resource_Status",
                "LOB.1", "Sub LOB", "Site", "Skills", "State", "Unique Agent",
                "Multi Skill", "Skill Name", "Skill Split"
            ],
            'prod_team_roster':[
                'FirstName', 'LastName', 'CN', 'OPID', 'Location', 'ZIPCode', 'City', 'BeelineTitle', 
                'Status\n[inTrainingorProduction]', 'PrimaryPlatform', 'PrimaryMarket', 'Worktype(FTC/ADJ/COB)', 
                'LOB', "Supervisor'sFullName", "Supervisor'sCN#", 'UserStatus', 'PartofProduction', 'Production%', 
                'NewWorkType', 'State', 'CenteneMailId', 'NTTMailID'
            ],
            
        }

    def forecast_tabs(self,forecast_month, forecast_year):
        db_manager = self.core_utils.get_db_manager(ForecastModel, limit=1, skip=0)
        data = db_manager.read_db(forecast_month, forecast_year)
        if len(data['records'])<1:
            return {}
        filename = data['records'][0]['UploadedFile']
        db_manager = self.core_utils.get_db_manager(ForecastMonthsModel, limit=1, skip=0)
        tabs = db_manager.search_db(['UploadedFile'], [filename])
        tab_months = {k:v for k, v in tabs["records"][0].items() if k not in {'CreatedBy', 'id', 'CreatedDateTime', 'UploadedFile'}}
        return tab_months
    
    def forecast_columns(self, forecast_month, forecast_year):
        tab_months = self.forecast_tabs(forecast_month, forecast_year)
        
        column_tuple = self.MAPPING['forecast']
        return [
            (t[0], tab_months.get(t[1], t[1])) 
            for t in column_tuple
        ]
    
    def forecast_schema(self, month_map, input_data):
        output_schema = {}
        for m_key, month in month_map.items():
            client_forecast = input_data.get(f"Client_Forecast_{m_key}", 0)
            fte_required = input_data.get(f"FTE_Required_{m_key}", 0)
            fte_avail = input_data.get(f"FTE_Avail_{m_key}", 0)
            capacity = input_data.get(f"Capacity_{m_key}", 0)
            row = {
                "main lob": input_data.get("Centene_Capacity_Plan_Main_LOB", ""),
                "state": input_data.get("Centene_Capacity_Plan_State", ""),
                "worktype": input_data.get("Centene_Capacity_Plan_Case_Type", ""),
                "client forecast": str(client_forecast),
                "fte required": str(fte_required),
                "fte avail": str(fte_avail),
                "capacity": str(capacity)
            }
            output_schema[month] = [row]
        return output_schema
    
    def forecast_totals(self, month_map, summation_data:Dict[str, int]):
        totals = {}
        for m_key, month in month_map.items():
            sum_of_client_forecast = summation_data.get(f"Client_Forecast_{m_key}", 0)
            sum_of_fte_required = summation_data.get(f"FTE_Required_{m_key}", 0)
            sum_of_fte_avail = summation_data.get(f"FTE_Avail_{m_key}", 0)
            sum_of_capacity = summation_data.get(f"Capacity_{m_key}", 0)

            row = {
                "client forecast": str(sum_of_client_forecast),
                "fte required": str(sum_of_fte_required),
                "fte avail": str(sum_of_fte_avail),
                "capacity": str(sum_of_capacity)
            }
            totals[month]= row
        return totals

    def forecast_month_data(self,data, month):
        """
        Extracts and returns data for the specified month from the input structure.
        
        Args:
            data (list): The input data list of dictionary.
            month (str): The month to extract (e.g., 'March').
            
        Returns:
            list: A list of data entries for the specified month.
        """
        month_data = []
        for entry in data:
            if month in entry:
                month_data.extend(entry[month])
        return month_data
    

def to_title_case(field):
    # 1. Replace underscores with spaces
    field = field.replace("_", " ")
    tokens:List[str] = []
    # 2. Tokenize: Find all runs of ALLCAPS, CamelCase, and lowercase
    # Regex: Find sequences of [A-Z][A-Z0-9]+ (all caps), or [A-Z][a-z0-9]+, or [a-z0-9]+
    for part in field.split():
        matches = re.findall(r'[A-Z]{2,}(?=\s|[A-Z][a-z]|$)|[A-Z]?[a-z0-9]+|[A-Z]+', part)
        tokens.extend(matches)
    # 3. Capitalize single camel words, but keep ALLCAPS as is
    result = []
    for tok in tokens:
        if tok.isupper():
            result.append(tok)
        else:
            result.append(tok.upper())
    return ' '.join(result)

def test_sum_metrics_example() -> None:
    """
    Reuses your existing database (no seeding). Prints the aggregated dict for:
      - month='March', year=2025,
      - main_lob='Amisys Medicaid DOMESTIC',
      - case_type='ADJ-Basic/NON MMP'
    """
    manager = DBManager(
        database_url=DATABASE_URL,
        Model=ForecastModel,
        limit=0,
        skip=0,
        select_columns=None,
    )

    result = manager.sum_metrics(
        month="March",
        year=2025,
        main_lob="Amisys Medicaid DOMESTIC",
        case_type="ADJ-Basic/NON MMP",
    )

    # Pretty-print for quick manual verification
    print(json.dumps(result, indent=2, sort_keys=True))
        
if __name__ == "__main__":
    preprocessor = PreProcessing(file_id='forecast')
    # file_path = os.path.join(BASE_DIR, "logics", "data", "Input", "NTT Forecast - Capacity and HC - Feb 2025 V2.xlsx")
    file_path = r"C:\Users\336155\OneDrive - NTT DATA North America\input files\forecast data\NTT Forecast_Capacity and HC_v1_February_2025.xlsx"
    dfs = preprocessor.process_forecast_file(file_path)

    output_base = BASE_DIR
    for folder, subdict in dfs.items():
        folder_path = os.path.join(output_base, folder)
        os.makedirs(folder_path, exist_ok=True)
        for key, df in subdict.items():
            file_path = os.path.join(folder_path, f"{key}.xlsx")
            df.to_excel(file_path)

    # test_sum_metrics_example()

    # ...existing code...
    


