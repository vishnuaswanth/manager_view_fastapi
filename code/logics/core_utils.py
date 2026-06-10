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
    ForecastMonthsModel,
    AllocationReportsModel
)
import warnings
# warnings.filterwarnings("ignore")
from code.settings import  (
    MODE,
    SQLITE_DATABASE_URL,
    MSSQL_DATABASE_URL,
    BASE_DIR
)
from code.logics.manager_view import parse_main_lob
from code.logics.month_code_utils import format_month_year_code, parse_month_year_code, is_month_year_code


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
        'allocation_reports': AllocationReportsModel,
    }
    ALL_MODELS_KEY = 'All'

    if file_id.lower() == ALL_MODELS_KEY.lower():
        return {key: value for key, value in MODEL_FIELD_MAPPING.items() if key not in ['upload_roster', 'allocation_reports']}

    model = MODEL_FIELD_MAPPING.get(file_id.lower())
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")

    return model

def _safe_filename(text: str) -> str:
    """Trim at first asterisk and normalise characters for use as filenames and search query tokens."""
    text = re.match(r'^[^*]*', str(text)).group(0) if text else ""
    text = re.sub(r'\s*&\s*', ' and ', text)
    text = re.sub(r'\s*/\s*', ' or ', text)
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
    df_multi = df_multi.drop(columns=cols_to_drop)
    try:
        # Process each column for type and fill NaNs
        df_multi = df_multi.apply(clean_series, axis=0)
    except Exception as e:
        logger.error(f"Error occured while cleaning summary data: {e}")
    return df_multi

def extract_summary_tables(filestream, sheet_name: str, client_names: list) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """
    Extracts tables from the summary sheet of the given Excel file stream.
    sheet_name must be the actual tab name as it appears in the file (resolved by the caller).
    Returns a tuple of:
      - dict {safe_filename: dataframe} for processable tables
      - list of sheet names referenced by '*Use {sheet_name} Tab to provide...' headers
    Tables whose headers contain '*Rollup/Formulas' or '*Use ... Tab to provide...' are skipped.
    """
    forecast_excel_df = pd.read_excel(filestream, sheet_name=sheet_name, dtype=str, header=None)
    start_index = 0
    max_rows = len(forecast_excel_df)
    empty_row_count = 0
    tables_dict = {}
    referenced_sheets = []


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
                    return tables_dict, referenced_sheets
            else:
                empty_row_count = 0

        if not found_start:
            break

        end_index = start_index + 1
        while end_index < max_rows:
            if forecast_excel_df.iloc[end_index].astype(str).str.contains("Total", case=False, na=False).any():
                if (end_index + 1 < max_rows and forecast_excel_df.iloc[end_index + 1].isna().all()):
                    break
            end_index += 1

        if end_index >= max_rows - 1:
            end_index = max_rows - 1

        table_df = forecast_excel_df.iloc[start_index:end_index + 1]
        table_df = table_df.dropna(axis=1, how='all')
        # Convert to string once for efficient filtering
        str_df = table_df.astype(str)
        # Filter out rows where any cell starts with "YYYY"
        yyyy_mask = ~str_df.apply(lambda x: x.str.startswith("YYYY", na=False)).any(axis=1)
        # Filter out rows where any cell contains "Total" (including "Total Excluding BOT", etc.)
        total_mask = ~str_df.apply(lambda x: x.str.contains("Total", case=False, na=False)).any(axis=1)
        table_df = table_df[yyyy_mask & total_mask]

        # Skip tables that defer to another tab for capacity
        # Header format: "{Table Name} *Use {sheet_name} Tab to provide Capacity and Headcount"
        use_match = re.search(r'\*Use\s+(.+?)\s+Tab\s+to\s+provide', str(header_value), re.IGNORECASE)
        if use_match:
            referenced_sheets.append(use_match.group(1).strip())
            start_index = end_index + 2
            continue
        # Skip rollup/formula-only summary tables
        # Header format: "{Table Name} *Rollup/Formulas"
        if '*rollup' in str(header_value).lower() or any(x in safe_filename.upper() for x in ["COMBINED"]):
            start_index = end_index + 2
            continue

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
        df_multi = df_multi.reset_index(drop=True)
        df_multi = clean_multiindex_df(df_multi)
        tables_dict[safe_filename] = df_multi

        start_index = end_index + 2

    return tables_dict, referenced_sheets

class PreProcessing:

    # ── Forecast sheet registry ────────────────────────────────────────────────
    # Single source of truth for all known forecast Excel tab names.
    # Sheet name lookup is case-insensitive at runtime.
    #
    # Categories:
    #   "amisys_medicaid" – Medicaid domestic/global sheets (3 header rows)
    #   "amisys_mmp"      – MMP state-level sheet (2 header rows, split by state)
    #   "amisys_aligned_dual"     – Aligned Dual state-level sheet (dynamic parsing)
    #   "summary"         – Summary sheet (mandatory; parsed separately)
    #
    # To add a new sheet type:
    #   1. Add its exact Excel tab name and category here.
    #   2. Add a mapping entry in FORECAST_CATEGORY_HANDLERS with dfs_key and handler name.
    #   3. Implement the handler method (follow the existing handler signatures).
    FORECAST_SHEET_REGISTRY: Dict[str, str] = {
        "Amisys Medicaid DOMESTIC":        "amisys_medicaid",
        "Amisys Medicaid GLOBAL":          "amisys_medicaid",
        "Amisys MMP State Level":          "amisys_mmp",
        "Amisys Aligned Dual State Level": "amisys_aligned_dual",
        # "New Sheet Name":                "new_category",
    }

    # Summary sheet is mandatory and handled independently of the registry above.
    FORECAST_SUMMARY_SHEET = "Forecast v Capacity Summary"

    # Client/platform names used to locate table boundaries in the summary sheet.
    # Add new platform names here when onboarding additional clients.
    SUMMARY_CLIENT_NAMES: list = ["amisys", "xcelys", "facets"]

    # ── Category → handler mapping ─────────────────────────────────────────────
    # Maps each registry category to:
    #   "dfs_key" – the key used in the dfs dict returned by process_forecast_file()
    #   "handler" – the private method that parses the sheet AND produces ForecastModel rows
    #
    # Each handler signature (detail sheets):
    #   _handle_<category>_sheet(self, file_stream, sheet_name, month_codes, month_name_to_key, target_cph_lookup) -> pd.DataFrame
    # Summary handler signature:
    #   _handle_summary_sheet(self, raw_summary_dfs, month_codes, month_name_to_key, target_cph_lookup) -> pd.DataFrame
    #   (called directly in process_forecast_file, not through registry dispatch)
    #
    # To add a new sheet category:
    #   1. Add the sheet name + category in FORECAST_SHEET_REGISTRY above.
    #   2. Add an entry here with dfs_key and handler name.
    #   3. Implement the handler — parse the sheet, build rows via _build_forecast_row,
    #      return pd.DataFrame(rows, columns=self.MAPPING['forecast']).
    FORECAST_CATEGORY_HANDLERS: Dict[str, Dict[str, Optional[str]]] = {
        "amisys_medicaid":    {"dfs_key": "amisys_medicaid",    "handler": "_handle_amisys_medicaid_sheet"},
        "amisys_mmp":         {"dfs_key": "amisys_mmp",         "handler": "_handle_amisys_mmp_sheet"},
        "amisys_aligned_dual":{"dfs_key": "amisys_aligned_dual","handler": "_handle_amisys_aligned_dual_sheet"},
        "summary":            {"dfs_key": "summary",            "handler": "_handle_summary_sheet"},  # called directly
        # "new_category":     {"dfs_key": "new_key",            "handler": "_handle_new_sheet"},
    }

    # Category key for the summary sheet — must match the "summary" entry above.
    FORECAST_SUMMARY_CATEGORY = "summary"

    def __init__(self, file_id, ):
        self.file_id = file_id
        self.month_codes = {}
        self.all_sheet_names: list = []
        self.unprocessed_referenced_sheets: list = []
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
        # Extract unique months in calendar order, deduplicating abbr_to_full values
        # (abbr_to_full maps both 'Sep' and 'Sept' to 'September', so without dedup
        # 'September' would appear twice and create a spurious Month7 key).
        _month_set = set(second_level)
        unique_months = list(dict.fromkeys(
            m for m in self.abbr_to_full.values() if m in _month_set
        ))
        self.month_codes = {f"Month{i+1}": month for i, month in enumerate(unique_months)}


        # df = pd.read_excel(path, header=list(range(header_rows)))
        # Flatten the MultiIndex columns
        df.columns = [
            "_".join([str(i) for i in col if str(i) != 'nan']).strip("_")
            for col in df.columns.values
        ]

        # Remove unnamed columns (often contain index values)
        unnamed_cols = [col for col in df.columns if 'Unnamed' in str(col)]
        if unnamed_cols:
            df = df.drop(columns=unnamed_cols)
            logger.info(f"Removed {len(unnamed_cols)} unnamed column(s) from forecast data")

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

    def preprocess_forecast_df(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._process_forecast_df(df)  # flattens MultiIndex, sets self.month_codes

        # Name-based mapping — not positional — so column order of the MultiIndex doesn't matter.
        # get_forecast_demand_from_db produces month-grouped columns; MAPPING is section-grouped.
        # Positional assignment would put FTE_Required_April into Client_Forecast_Month2, etc.
        month_name_to_key = {v: k for k, v in self.month_codes.items()}
        _META_MAP = {
            "Centene Capacity plan_Main LOB":     "Centene_Capacity_Plan_Main_LOB",
            "Centene Capacity plan_State":        "Centene_Capacity_Plan_State",
            "Centene Capacity plan_Case type":    "Centene_Capacity_Plan_Case_Type",
            "Centene Capacity plan_Call Type ID": "Centene_Capacity_Plan_Call_Type_ID",
            "Centene Capacity plan_Target CPH":   "Centene_Capacity_Plan_Target_CPH",
        }
        _SECTION_MAP = {
            "Client Forecast": "Client_Forecast",
            "FTE Required":    "FTE_Required",
            "FTE Avail":       "FTE_Avail",
            "Capacity":        "Capacity",
        }
        rename_dict = {}
        for col in df.columns:
            if col in _META_MAP:
                rename_dict[col] = _META_MAP[col]
            else:
                for section_src, section_dst in _SECTION_MAP.items():
                    if col.startswith(section_src + "_"):
                        month_name = col[len(section_src) + 1:]
                        m_key = month_name_to_key.get(month_name)
                        if m_key:
                            rename_dict[col] = f"{section_dst}_{m_key}"
                        break
        df = df.rename(columns=rename_dict)

        columns = self.MAPPING[self.file_id]
        return df[columns]

    def preprocess_roster(self, df: pd.DataFrame) -> pd.DataFrame:
        expected = self.MAPPING["roster"]
        df.columns = df.columns.str.strip()
        df = df[expected] if all(col in df.columns for col in expected) else pd.read_excel(df, names=expected)
        # Vectorized string processing for all columns
        df = df.apply(lambda x: x.fillna("").astype(str).str.strip())
        return df

    def preprocess_skilling(self, df: pd.DataFrame) -> pd.DataFrame:
        df.columns = self.MAPPING["skilling"]
        df.columns = df.columns.str.strip()
        int_cols = ['Unique_Agent', 'Multi_Skill']
        float_cols = ['Skill_Split']

        # Process numeric columns
        for col in int_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
        for col in float_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0).astype(float)

        # Process all string columns at once with vectorized operations
        string_cols = [col for col in df.columns if col not in int_cols and col not in float_cols]
        if string_cols:
            df[string_cols] = df[string_cols].apply(lambda x: x.fillna("").astype(str).str.strip())
        return df

    def get_model_keys(self):
        return self.model_keys.get(self.file_id,[])

    @staticmethod
    def _read_aligned_dual_sheet(file_stream) -> Dict[str, pd.DataFrame]:
        """
        Parse 'Amisys Aligned Dual State Level' sheet into normalized flat DataFrames.

        Dynamically discovers:
        - Data start row by finding the row that contains 'Month' and 'State' labels
        - Medicare / Medicaid section boundaries by scanning header rows
        - Work type columns (FTC, ADJ, COR, OMN, APP, ...) by name — picks up new
          types automatically and is unaffected by column insertions/deletions

        Columns in each returned DF: Month, State, Area, <case_type_1>, ...
        Case types are normalised to "<PREFIX> MCARE" or "<PREFIX> MCAID".
        """
        # Work-type keyword prefixes to recognise in header cells
        _WT_PREFIXES = ('ftc', 'adj', 'cor', 'omn', 'app')

        def _normalize_case_type(raw: str, section: str) -> str:
            """'FTC-Medicare Aligned Duals' → 'FTC MCARE', etc."""
            suffix = 'MCARE' if 'medicare' in section.lower() else 'MCAID'
            # prefix = first token before '-' or ' '
            prefix = raw.strip().upper().replace('-', ' ').split()[0]
            return f'{prefix} {suffix}'

        # ── Read the entire sheet without skipping any rows ───────────────────
        df_full = pd.read_excel(
            file_stream,
            sheet_name='Amisys Aligned Dual State Level',
            header=None, dtype=str
        )

        if df_full.empty:
            return {}

        total_rows, total_cols = df_full.shape

        # ── 1. Find anchor row: last header row containing 'Month' + 'State' ──
        # Data starts on the row immediately after this one.
        anchor_row_idx = None
        for i in range(min(10, total_rows)):
            row_lower = [str(v).strip().lower() for v in df_full.iloc[i]]
            if 'month' in row_lower and 'state' in row_lower:
                anchor_row_idx = i
                break

        if anchor_row_idx is None:
            logger.warning(
                "Aligned Dual sheet: could not detect anchor row with 'Month'/'State' — "
                "falling back to skiprows=5"
            )
            anchor_row_idx = 4
        data_start_row = anchor_row_idx + 1

        anchor_row = [str(v).strip().lower() for v in df_full.iloc[anchor_row_idx]]
        month_col = next((j for j, v in enumerate(anchor_row) if v == 'month'), None)
        state_col = next((j for j, v in enumerate(anchor_row) if v == 'state'), None)
        # All 'area' columns (one per section)
        area_cols = [j for j, v in enumerate(anchor_row) if v == 'area']

        if month_col is None or state_col is None:
            raise ValueError(
                "Aligned Dual sheet: 'Month' and/or 'State' columns not found in "
                f"header row {anchor_row_idx}."
            )

        # ── 2. Find section boundaries (Medicare / Medicaid) ─────────────────
        # Scan ALL header rows for cells containing 'medicare'/'medicaid'.
        section_positions: Dict[str, int] = {}  # section_name -> leftmost col
        for i in range(data_start_row):
            for j in range(total_cols):
                cell = str(df_full.iloc[i, j]).strip().lower()
                if not cell or cell == 'nan':
                    continue
                if 'medicare' in cell and 'medicaid' not in cell and 'Medicare' not in section_positions:
                    section_positions['Medicare'] = j
                elif 'medicaid' in cell and 'Medicaid' not in section_positions:
                    section_positions['Medicaid'] = j

        if not section_positions:
            raise ValueError(
                "Aligned Dual sheet: could not find Medicare/Medicaid section headers."
            )

        # Build column ranges per section (each section ends where the next begins)
        sorted_sections = sorted(section_positions.items(), key=lambda x: x[1])
        section_col_ranges: Dict[str, tuple] = {}
        for idx, (sec_name, sec_start) in enumerate(sorted_sections):
            sec_end = sorted_sections[idx + 1][1] if idx + 1 < len(sorted_sections) else total_cols
            section_col_ranges[sec_name] = (sec_start, sec_end)

        # ── 3. Find work-type header row ──────────────────────────────────────
        # The row with the most cells that start with a known prefix.
        wt_row_idx = None
        best_count = 0
        for i in range(data_start_row):
            row_vals = [str(v).strip().lower() for v in df_full.iloc[i]]
            count = sum(1 for v in row_vals if any(v.startswith(kw) for kw in _WT_PREFIXES))
            if count > best_count:
                best_count = count
                wt_row_idx = i

        if wt_row_idx is None or best_count < 1:
            raise ValueError(
                "Aligned Dual sheet: could not find a header row containing work-type "
                f"names ({', '.join(_WT_PREFIXES).upper()}, ...)."
            )

        wt_row_vals = [str(v).strip() for v in df_full.iloc[wt_row_idx]]

        # ── 4. Build a DataFrame for each section ────────────────────────────
        df_data = df_full.iloc[data_start_row:].reset_index(drop=True)

        def _build_section(sec_name: str, col_start: int, col_end: int) -> pd.DataFrame:
            # Area column for this section: first 'area' within the section range
            area_col = next((j for j in area_cols if col_start <= j < col_end), None)

            # Work-type columns within this section
            # Keep only the FIRST column for each normalized name to avoid
            # duplicates when both forecast and capacity columns share a prefix
            # (e.g. 'FTC-Medicare Aligned Duals' and 'FTC-Medicare Aligned Duals Capacity'
            # both normalize to 'FTC MCARE').
            work_type_cols: Dict[int, str] = {}
            _seen_wt: set = set()
            for j in range(col_start, min(col_end, len(wt_row_vals))):
                raw = wt_row_vals[j]
                if not raw or raw.lower() == 'nan':
                    continue
                if any(raw.lower().startswith(kw) for kw in _WT_PREFIXES):
                    normalized = _normalize_case_type(raw, sec_name)
                    if normalized not in _seen_wt:
                        work_type_cols[j] = normalized
                        _seen_wt.add(normalized)

            if not work_type_cols:
                logger.warning(f"Aligned Dual sheet: no work-type columns found for section '{sec_name}'")
                return pd.DataFrame()

            col_map: Dict[int, str] = {month_col: 'Month', state_col: 'State'}
            if area_col is not None:
                col_map[area_col] = 'Area'
            col_map.update(work_type_cols)

            available = [c for c in sorted(col_map.keys()) if c < total_cols]
            sub = df_data.iloc[:, available].copy()
            sub.columns = [col_map[c] for c in available]

            # Drop rows without State/Month
            sub = sub[sub['State'].astype(str).str.strip().str.lower().isin(
                ['', 'nan']) == False]
            sub = sub[sub['Month'].astype(str).str.strip().str.lower().isin(
                ['', 'nan']) == False]
            sub = sub.dropna(subset=['State', 'Month'])

            # Numeric conversion for work-type value columns
            for col_name in work_type_cols.values():
                if col_name in sub.columns:
                    sub[col_name] = pd.to_numeric(sub[col_name], errors='coerce').fillna(0)

            return sub.reset_index(drop=True)

        # ── 5. Split each section by Global / Domestic area ──────────────────
        parts: Dict[str, pd.DataFrame] = {}
        for sec_name, (col_start, col_end) in section_col_ranges.items():
            sec_df = _build_section(sec_name, col_start, col_end)
            if sec_df.empty or 'Area' not in sec_df.columns:
                logger.warning(f"Aligned Dual sheet: no data produced for section '{sec_name}'")
                continue
            for area in ['Global', 'Domestic']:
                mask = sec_df['Area'].astype(str).str.strip().str.lower() == area.lower()
                subset = sec_df[mask].reset_index(drop=True)
                if not subset.empty:
                    parts[f'AMISYS Aligned Dual {sec_name} {area}'] = subset

        logger.info(
            f"Aligned Dual sheet parsed dynamically: "
            f"anchor_row={anchor_row_idx}, data_start={data_start_row}, "
            f"sections={list(section_col_ranges.keys())}, "
            f"wt_row={wt_row_idx}, segments={list(parts.keys())}"
        )
        return parts

    @staticmethod
    def _read_multi_sheet(
        file_stream: Union[str, BinaryIO],
        sheet: str,
        *,
        header_depth: int = 3,
        skiprows: int = 1,
        skipfooter: int = 0,
    ) -> pd.DataFrame:
        """Read an Excel sheet with a multi-row header and normalize 'Unnamed'.

        After reading, drops:
        - Columns where every data cell is NaN (fully empty columns)
        - Rows where every data cell is NaN (fully empty rows, e.g. spacer rows)
        """
        headers = list(range(0, header_depth))
        df = pd.read_excel(
            file_stream, sheet_name=sheet, header=headers, dtype=str,
            skiprows=skiprows, skipfooter=skipfooter
        )
        df.columns = pd.MultiIndex.from_tuples(
            tuple("" if "Unnamed" in str(lvl) else lvl for lvl in tup)
            for tup in df.columns
        )
        # Drop fully-empty columns and rows (spacers / totals that weren't caught by skipfooter)
        df = df.dropna(how='all', axis=1)
        df = df.dropna(how='all', axis=0).reset_index(drop=True)
        return df

    # ── Sheet handler methods ──────────────────────────────────────────────────
    # Each handler parses its Excel sheet AND produces ForecastModel-ready rows.
    # All return pd.DataFrame with columns = self.MAPPING['forecast'].
    #
    # Detail handler signature:
    #   _handle_*_sheet(self, file_stream, sheet_name, month_codes, month_name_to_key, target_cph_lookup) -> pd.DataFrame
    # Summary handler is called directly (receives already-parsed raw_summary_dfs dict).

    def _handle_amisys_medicaid_sheet(
        self, file_stream, sheet_name: str,
        month_codes: Dict[str, str], month_name_to_key: Dict[str, str],
        target_cph_lookup: Dict, month_year_map: Optional[Dict[str, int]] = None,
    ) -> pd.DataFrame:
        """Parse Medicaid sheet (3 header rows) and produce ForecastModel rows."""
        lob = sheet_name
        df = self._read_multi_sheet(file_stream, sheet_name, header_depth=3, skiprows=1)

        work_types = sorted(set(
            col[2] for col in df.columns
            if 'forecast - volume' in str(col[0]).lower()
            and str(col[2]).strip()
            and 'total' not in str(col[2]).lower()
        ))

        if ('', '', 'State') not in df.columns:
            logger.warning(f"Medicaid sheet '{sheet_name}': ('','','State') column not found — skipping")
            return pd.DataFrame(columns=self.MAPPING['forecast'])

        states = [
            s for s in df[('', '', 'State')].dropna().unique()
            if isinstance(s, str) and s.strip() not in ('', 'nan')
        ]

        if not work_types or not states:
            logger.warning(f"Medicaid sheet '{sheet_name}': work_types={work_types}, states={states}")
            return pd.DataFrame(columns=self.MAPPING['forecast'])

        rows = []
        for state in states:
            for work_type in work_types:
                rows.append(self._build_forecast_row(
                    lob=lob, state=state, work_type=work_type,
                    df=df, month_codes=month_codes, month_name_to_key=month_name_to_key,
                    target_cph_lookup=target_cph_lookup, sheet_type='amisys_medicaid',
                    month_year_map=month_year_map,
                ))
        logger.info(f"Medicaid sheet '{sheet_name}': {len(rows)} forecast rows produced")
        return pd.DataFrame(rows, columns=self.MAPPING['forecast'])

    def _handle_amisys_mmp_sheet(
        self, file_stream, sheet_name: str,
        month_codes: Dict[str, str], month_name_to_key: Dict[str, str],
        target_cph_lookup: Dict, month_year_map: Optional[Dict[str, int]] = None,
    ) -> pd.DataFrame:
        """Parse MMP state-level sheet (3 header rows) and produce ForecastModel rows.

        Sheet structure:
          Row 0: group headers (FTC, ADJ, ...) — merged cells forward-filled
          Row 1: work type names (FTC-Medicare MMP, FTC-Medicaid MMP, ...)
          Row 2: 'Forecast' for data cols; 'Area' at the last relevant column
        Area column value drives LOB: 'Domestic' → 'Amisys MMP Domestic', etc.
        Work type names: 'FTC-Medicare MMP' → 'FTC MCARE', 'FTC-Medicaid MMP' → 'FTC MCAID'.
        """
        # Read raw (no header), drop entirely empty rows, then extract header rows
        raw = pd.read_excel(file_stream, sheet_name=sheet_name, header=None)
        raw = raw.dropna(how="all").reset_index(drop=True)

        def _norm(v):
            s = str(v).strip()
            return "" if s.lower() in ("nan", "") else s

        # Row 0 has merged cells — forward-fill so each column inherits its group label
        h0 = pd.Series(raw.iloc[0]).ffill().tolist()
        h1 = raw.iloc[1].tolist()
        h2 = raw.iloc[2].tolist()

        columns = pd.MultiIndex.from_arrays([
            [_norm(v) for v in h0],
            [_norm(v) for v in h1],
            [_norm(v) for v in h2],
        ])
        raw = pd.DataFrame(raw.iloc[3:].values, columns=columns).reset_index(drop=True)
        raw = raw.dropna(how="all").reset_index(drop=True)

        area_col_idx = next(
            (i for i, col in enumerate(raw.columns) if col[2].strip().lower() == "area"), None
        )
        if area_col_idx is None:
            raise HTTPException(
                status_code=400,
                detail=f"Sheet '{sheet_name}': 'Area' column not found in 3rd header row.",
            )

        df = raw.iloc[:, :area_col_idx + 1].copy()
        df = df.dropna(how="all").reset_index(drop=True)

        month_col = next((c for c in df.columns if c[2].strip().lower() == "month"), None)
        state_col  = next((c for c in df.columns if c[2].strip().lower() == "state"), None)
        area_col   = df.columns[area_col_idx]

        if not month_col or not state_col:
            raise HTTPException(
                status_code=400,
                detail=f"Sheet '{sheet_name}': 'Month' or 'State' column not found in 3rd header row.",
            )

        work_type_cols = [c for c in df.columns if c[2].strip().lower() == "forecast"]

        def _get_work_type_name(col_tuple) -> str:
            name = str(col_tuple[1] if col_tuple[1] else col_tuple[0])
            name = name.replace("-Medicare MMP", " MCARE").replace("-Medicaid MMP", " MCAID")
            name = name.replace("-Medicare", " MCARE").replace("-Medicaid", " MCAID")
            return name

        rows = []
        for area_val in df[area_col].dropna().unique():
            area_str = str(area_val).strip()
            lob_name = f"Amisys MMP {area_str}"
            area_df  = df[df[area_col].astype(str).str.strip() == area_str]
            states   = [
                s for s in area_df[state_col].dropna().unique()
                if str(s).strip() not in ("", "nan")
            ]
            for state in states:
                state_df = area_df[area_df[state_col] == state]
                for wt_col in work_type_cols:
                    rows.append(self._build_forecast_row(
                        lob=lob_name,
                        state=str(state).strip(),
                        work_type=_get_work_type_name(wt_col),
                        df=state_df,
                        month_codes=month_codes,
                        month_name_to_key=month_name_to_key,
                        target_cph_lookup=target_cph_lookup,
                        sheet_type="amisys_mmp",
                        month_col=month_col,
                        value_col=wt_col,
                        month_year_map=month_year_map,
                    ))

        logger.info(f"MMP sheet '{sheet_name}': {len(rows)} forecast rows produced")
        return pd.DataFrame(rows, columns=self.MAPPING['forecast'])

    def _handle_amisys_aligned_dual_sheet(
        self, file_stream, sheet_name: str,
        month_codes: Dict[str, str], month_name_to_key: Dict[str, str],
        target_cph_lookup: Dict, month_year_map: Optional[Dict[str, int]] = None,
    ) -> pd.DataFrame:
        """Parse Aligned Dual sheet (dynamic structure) and produce ForecastModel rows."""
        result = self._read_aligned_dual_sheet(file_stream)
        rows = []
        for lob_name, df in result.items():
            if df is None or df.empty:
                continue
            meta_cols = {'Month', 'State', 'Area'}
            work_types = [c for c in df.columns if c not in meta_cols]
            if 'State' not in df.columns or not work_types:
                logger.warning(f"Aligned Dual segment '{lob_name}': State column or work types missing")
                continue
            states = df['State'].dropna().unique().tolist()
            for state in states:
                state_df = df[df['State'] == state]
                for work_type in work_types:
                    rows.append(self._build_forecast_row(
                        lob=lob_name, state=state, work_type=work_type,
                        df=state_df, month_codes=month_codes, month_name_to_key=month_name_to_key,
                        target_cph_lookup=target_cph_lookup, sheet_type='amisys_aligned_dual',
                        month_year_map=month_year_map,
                    ))
        logger.info(f"Aligned Dual sheet '{sheet_name}': {len(rows)} forecast rows produced")
        return pd.DataFrame(rows, columns=self.MAPPING['forecast'])

    def _handle_summary_sheet(
        self,
        raw_summary_dfs: Dict[str, pd.DataFrame],
        month_codes: Dict[str, str],
        month_name_to_key: Dict[str, str],
        target_cph_lookup: Dict,
    ) -> pd.DataFrame:
        """Process parsed summary tables into ForecastModel rows.

        Also upserts Target CPH DB records when sheet values differ from the DB.
        CPH from the sheet takes priority over the DB value.
        target_cph_lookup is updated in-memory so subsequent detail handlers use
        the correct CPH for the same upload session.
        """
        from code.logics.target_cph_utils import upsert_target_cph_configuration

        rows = []
        for lob_key, df in raw_summary_dfs.items():
            if df is None or (hasattr(df, 'empty') and df.empty):
                continue
            lob_name = lob_key.strip()
            df = df.copy()
            df.columns = df.columns.map(
                lambda x: tuple("" if "Unnamed" in str(i) else i for i in x)
            )

            work_type_col = next(
                (c for c in df.columns
                 if len(c) >= 3 and str(c[2]).strip().lower() in ('work type', 'worktype', 'case type')),
                None,
            )
            if work_type_col is None:
                logger.warning(f"Summary table '{lob_key}': work type column not found — skipping")
                continue

            cph_col = next(
                (c for c in df.columns if len(c) >= 3 and str(c[2]).strip().lower() == 'cph'),
                None,
            )

            work_types = [
                str(wkt) for wkt in df[work_type_col].fillna('')
                if str(wkt).strip() and str(wkt).strip().lower() != 'total'
            ]

            for work_type in work_types:
                wt_rows = df[df[work_type_col] == work_type]

                # CPH from sheet takes priority over DB value
                if cph_col is not None and not wt_rows.empty:
                    sheet_cph = pd.to_numeric(wt_rows[cph_col].values[0], errors='coerce')
                    if pd.notna(sheet_cph) and float(sheet_cph) > 0:
                        sheet_cph_f = float(sheet_cph)
                        db_cph = target_cph_lookup.get(
                            (lob_name.lower(), work_type.strip().lower())
                        )
                        if db_cph is None or abs(db_cph - sheet_cph_f) > 0.001:
                            upsert_target_cph_configuration(lob_name, work_type, sheet_cph_f)
                        # Update in-memory lookup so detail handlers also use this value
                        target_cph_lookup[(lob_name.lower(), work_type.strip().lower())] = sheet_cph_f

                rows.append(self._build_forecast_row(
                    lob=lob_name, state='N/A', work_type=work_type,
                    df=df, month_codes=month_codes, month_name_to_key=month_name_to_key,
                    target_cph_lookup=target_cph_lookup, sheet_type='summary',
                ))

        logger.info(f"Summary sheet: {len(rows)} forecast rows produced")
        return pd.DataFrame(rows, columns=self.MAPPING['forecast'])

    @staticmethod
    def _compute_month_year_map(
        month_codes: Dict[str, str],
        upload_month: str,
        upload_year: int,
    ) -> Dict[str, int]:
        """Return {m_key: year} for each forecast month in month_codes.

        Handles year-boundary wrapping (e.g. November 2026 upload →
        Month1=December 2026, Month3=February 2027).
        """
        from calendar import month_name as cal_month_name
        month_names = list(cal_month_name)[1:]  # ['January', ..., 'December']
        month_to_num = {m: i + 1 for i, m in enumerate(month_names)}
        upload_month_num = month_to_num.get(upload_month)
        first_month_num = month_to_num.get(month_codes.get("Month1", ""))
        if not upload_month_num or not first_month_num:
            return {}
        # Month1 is in upload_year when it comes after the upload month; otherwise it
        # falls in upload_year + 1 (e.g. upload=December → Month1=January next year).
        first_forecast_year = upload_year if first_month_num > upload_month_num else upload_year + 1
        result = {}
        for m_key, month_name in month_codes.items():
            m_num = month_to_num.get(month_name)
            if m_num is None:
                continue
            result[m_key] = first_forecast_year if m_num >= first_month_num else first_forecast_year + 1
        return result

    def process_forecast_file(
        self,
        file_stream: Union[str, BinaryIO],
        upload_month: Optional[str] = None,
        upload_year: Optional[int] = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Parse the forecast Excel file and produce ForecastModel-ready DataFrames.
        Each value in the returned dict is a pd.DataFrame with columns = MAPPING['forecast'].

        Returns:
            dict: {
                "summary":            pd.DataFrame (ForecastModel rows),
                "amisys_medicaid":    pd.DataFrame (ForecastModel rows),
                "amisys_mmp":         pd.DataFrame (ForecastModel rows),
                "amisys_aligned_dual":pd.DataFrame (ForecastModel rows),
            }

        Raises:
            HTTPException(400): If the summary sheet is missing, unparseable, or has no months.
        """
        registry         = self.FORECAST_SHEET_REGISTRY
        handlers_map     = self.FORECAST_CATEGORY_HANDLERS
        summary_sheet    = self.FORECAST_SUMMARY_SHEET
        summary_dfs_key  = handlers_map[self.FORECAST_SUMMARY_CATEGORY]["dfs_key"]

        # Discover available sheets
        xl = pd.ExcelFile(file_stream)
        self.all_sheet_names = list(xl.sheet_names)
        # Lookup keyed by stripped+lowercased name → actual tab name for case-insensitive resolution
        sheet_lookup = {s.strip().lower(): s for s in xl.sheet_names}

        dfs: Dict[str, pd.DataFrame] = {}

        # ── Summary sheet FIRST (missing = error; present but bad = error) ───
        actual_summary_sheet = sheet_lookup.get(summary_sheet.strip().lower())
        if not actual_summary_sheet:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Required sheet '{summary_sheet}' is missing from the uploaded file. "
                    f"Please ensure the file contains this sheet before uploading."
                )
            )
        try:
            # raw_summary_dfs: {safe_filename: DataFrame} — used for month extraction and CPH upsert
            raw_summary_dfs, referenced_sheets = extract_summary_tables(
                file_stream, actual_summary_sheet, self.SUMMARY_CLIENT_NAMES
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to parse summary sheet '{summary_sheet}': {e}", exc_info=True)
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Sheet '{summary_sheet}' could not be parsed. "
                    f"Please verify the sheet layout has not changed (table headers, column structure). Error: {e}"
                )
            )
        logger.info(
            f"Parsed summary sheet '{summary_sheet}': "
            f"{len(raw_summary_dfs)} LOB table(s): "
            f"{', '.join(raw_summary_dfs.keys())}"
        )
        for safe_filename in raw_summary_dfs.keys():
            lob_components = parse_main_lob(safe_filename)
            if lob_components.get("platform") is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Could not determine platform (Amisys/Facets/Xcelys) for table '{safe_filename}' "
                        f"in sheet '{summary_sheet}'. Please check the table header name."
                    )
                )
        # Store raw DFs temporarily so month extraction can read them
        dfs[summary_dfs_key] = raw_summary_dfs

        # ── Check referenced sheets against known handlers ────────────────────
        known_detail_sheets = {name.strip().lower() for name in registry}
        self.unprocessed_referenced_sheets = [
            name for name in referenced_sheets
            if name.strip().lower() not in known_detail_sheets
        ]
        if self.unprocessed_referenced_sheets:
            logger.warning(
                f"Summary sheet references sheets with no handler: "
                f"{self.unprocessed_referenced_sheets}"
            )

        # ── Extract month codes from summary (mandatory) ─────────────────────────
        # raw_summary_dfs is stored in dfs[summary_dfs_key] at this point.
        raw_summary_dfs = dfs[summary_dfs_key]
        unique_months = []
        for _, df in raw_summary_dfs.items():
            if not df.empty and df.columns.nlevels == 4:
                unique_months = get_columns_between_column_names(df, 2, 'CPH', 'Work Type')
                if unique_months:
                    break
        if not unique_months:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Could not extract forecast month columns from sheet '{summary_sheet}'. "
                    "Please verify the summary table has month headers between the CPH and Work Type columns."
                )
            )
        first_month = unique_months[0]
        consecutive_months = generate_consecutive_months(first_month, 6)
        plain_codes = {f"Month{i+1}": month for i, month in enumerate(consecutive_months)}
        # month_name_to_key uses plain names — needed for reverse lookups within this parse session
        month_name_to_key = {v: k for k, v in plain_codes.items()}

        # ── Compute year for each forecast month ──────────────────────────────────
        month_year_map: Dict[str, int] = {}
        if upload_month and upload_year:
            month_year_map = self._compute_month_year_map(plain_codes, upload_month, upload_year)

        # Build month_codes: embed year ("Apr-2026") when available, else plain names
        if month_year_map:
            month_codes = {
                k: format_month_year_code(plain_codes[k], month_year_map[k])
                for k in plain_codes
            }
        else:
            month_codes = plain_codes

        logger.info(
            "Month codes derived from summary sheet: "
            + ", ".join(f"{k}={v}" for k, v in month_codes.items())
        )

        # ── Load Target CPH lookup ────────────────────────────────────────────────
        try:
            from code.logics.target_cph_utils import get_all_target_cph_as_dict
            target_cph_lookup = get_all_target_cph_as_dict()
        except Exception as e:
            logger.warning(f"Could not load Target CPH from DB: {e}. Using empty lookup.")
            target_cph_lookup = {}

        # ── Summary handler: produces ForecastModel rows + upserts CPH to DB ────
        dfs[summary_dfs_key] = self._handle_summary_sheet(
            raw_summary_dfs, month_codes, month_name_to_key, target_cph_lookup
        )

        # ── Detail sheets: only process sheets referenced by the summary ─────────
        # referenced_sheets comes from "*Use {name} Tab to provide..." headers in the summary.
        for ref_name in referenced_sheets:
            registry_name = next(
                (n for n in registry if n.strip().lower() == ref_name.strip().lower()), None
            )
            if not registry_name:
                continue  # unprocessed — already warned above
            category = registry[registry_name]
            config   = handlers_map.get(category)
            if not config or config["handler"] is None or config["handler"] == "_handle_summary_sheet":
                continue
            actual_sheet_name = sheet_lookup.get(ref_name.strip().lower())
            if not actual_sheet_name:
                logger.warning(f"Sheet '{ref_name}' referenced in summary but not found in file — skipping")
                continue
            try:
                sheet_df = getattr(self, config["handler"])(
                    file_stream, actual_sheet_name, month_codes, month_name_to_key,
                    target_cph_lookup,
                )
                dfs_key = config["dfs_key"]
                if dfs_key in dfs and not dfs[dfs_key].empty:
                    # Multiple sheets share the same dfs_key (e.g. Amisys Medicaid DOMESTIC + GLOBAL)
                    dfs[dfs_key] = pd.concat([dfs[dfs_key], sheet_df], ignore_index=True)
                else:
                    dfs[dfs_key] = sheet_df
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to parse '{category}' sheet '{actual_sheet_name}': {e}", exc_info=True)
                raise HTTPException(
                    status_code=400,
                    detail=f"Sheet '{actual_sheet_name}' could not be parsed. Error: {e}"
                )

        self.month_codes = month_codes
        return dfs

    @staticmethod
    def _get_temp_casetype(casetype: str) -> str:
        """Convert case type prefix to short form for Call Type ID."""
        casetype = str(casetype)
        if not casetype or casetype == 'nan':
            return ''
        ct = casetype.split("-")[0].lower()
        return {'app': 'appeal', 'omn': 'omni'}.get(ct, ct)

    def _build_forecast_row(
        self, lob: str, state: str, work_type: str,
        df: pd.DataFrame, month_codes: Dict[str, str], month_name_to_key: Dict[str, str],
        target_cph_lookup: Dict, sheet_type: str,
        month_col=None, value_col=None,
        month_year_map: Optional[Dict[str, int]] = None,
    ) -> Dict:
        """Build a single ForecastModel-compatible row dict with Client Forecast values."""
        target_cph = target_cph_lookup.get((lob.strip().lower(), work_type.strip().lower()), 0)
        call_type_id = f"{lob} {self._get_temp_casetype(work_type)}"

        row = {
            'Centene_Capacity_Plan_Main_LOB': lob,
            'Centene_Capacity_Plan_State': state,
            'Centene_Capacity_Plan_Case_Type': work_type,
            'Centene_Capacity_Plan_Call_Type_ID': call_type_id,
            'Centene_Capacity_Plan_Target_CPH': target_cph,
        }

        for m_key, month_code in month_codes.items():
            val = 0
            # Resolve plain month name + expected year from the code
            if is_month_year_code(month_code):
                month_name, expected_year = parse_month_year_code(month_code)
            else:
                month_name = month_code
                expected_year = month_year_map.get(m_key) if month_year_map else None
            try:
                if sheet_type == 'amisys_mmp':
                    # df is pre-filtered by state; month_col and value_col are 3-level MultiIndex keys
                    mask = df[month_col] == month_name
                    if expected_year is not None:
                        year_col = next((c for c in df.columns if str(c[2]).strip().lower() == 'year'), None)
                        if year_col is not None:
                            mask &= df[year_col].astype(str).str.strip() == str(expected_year)
                    filtered = df[mask]
                    if not filtered.empty:
                        val = pd.to_numeric(filtered[value_col].values[0], errors='coerce') or 0
                elif sheet_type == 'amisys_medicaid':
                    mask = (df[('', '', 'State')] == state) & (df[('', '', 'Month')] == month_name)
                    if expected_year is not None:
                        year_col = ('', '', 'Year')
                        if year_col in df.columns:
                            mask &= df[year_col].astype(str).str.strip() == str(expected_year)
                    filtered = df[mask]
                    if not filtered.empty:
                        for col in filtered.columns:
                            if 'forecast - volume' in str(col[0]).lower() and col[2] == work_type:
                                val = pd.to_numeric(filtered[col].values[0], errors='coerce') or 0
                                break
                elif sheet_type == 'amisys_aligned_dual':
                    # df is pre-filtered by state
                    mask = df['Month'] == month_name
                    if expected_year is not None and 'Year' in df.columns:
                        mask &= df['Year'].astype(str).str.strip() == str(expected_year)
                    filtered = df[mask]
                    if not filtered.empty and work_type in filtered.columns:
                        val = pd.to_numeric(filtered[work_type].values[0], errors='coerce') or 0
                elif sheet_type == 'summary':
                    work_type_col = None
                    for col in df.columns:
                        if len(col) >= 3 and str(col[2]).lower() in ['work type', 'worktype', 'case type']:
                            work_type_col = col
                            break
                    if work_type_col is not None:
                        filtered = df[df[work_type_col] == work_type]
                        if not filtered.empty:
                            for col in df.columns:
                                if len(col) >= 3 and col[2] == month_name:
                                    val = pd.to_numeric(filtered[col].values[0], errors='coerce') or 0
                                    break
            except Exception:
                val = 0

            row[f'Client_Forecast_{m_key}'] = int(round(float(val))) if val and pd.notna(val) else 0
            row[f'FTE_Required_{m_key}'] = 0
            row[f'FTE_Avail_{m_key}'] = 0
            row[f'Capacity_{m_key}'] = 0

        return row

    def extract_forecast_demand(
        self,
        dfs: Dict[str, pd.DataFrame],
        month_codes: Optional[Dict[str, str]] = None,
        target_cph_lookup: Optional[Dict] = None,
    ) -> pd.DataFrame:
        """
        Combine all ForecastModel DataFrames produced by process_forecast_file.

        Each value in dfs is a pd.DataFrame with columns = MAPPING['forecast'],
        already produced by the sheet handlers. This method simply concatenates them.

        Args:
            dfs: Output of process_forecast_file — {dfs_key: pd.DataFrame}
            month_codes: Unused (kept for call-site compatibility).
            target_cph_lookup: Unused (kept for call-site compatibility).

        Returns:
            Single DataFrame with all ForecastModel rows, ready for DB insertion.
        """
        sheets = [
            df for df in dfs.values()
            if isinstance(df, pd.DataFrame) and not df.empty
        ]
        if not sheets:
            return pd.DataFrame(columns=self.MAPPING['forecast'])
        return pd.concat(sheets, ignore_index=True)


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
        with db_manager.SessionLocal() as session:
            record = session.query(ForecastMonthsModel).filter(
                ForecastMonthsModel.UploadedFile == filename
            ).order_by(
                ForecastMonthsModel.CreatedDateTime.desc()
            ).first()
        if not record:
            return {}
        tab_months = {f"Month{i}": getattr(record, f"Month{i}") for i in range(1, 7)}
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



