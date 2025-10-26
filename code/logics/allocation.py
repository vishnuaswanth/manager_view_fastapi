import sys
import os
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from datetime import datetime
import numpy as np
from typing import List
import logging

from code .logics.core_utils import PreProcessing
from code.logics.export_utils import (
    get_latest_or_requested_dataframe,
    update_forecast_data,
    get_forecast_months_list,
    get_all_model_dataframes_dict,
    get_calculations_data
)

from code.logics.summary_utils import update_summary_data
import pandas as pd
from code.settings import BASE_DIR

logger = logging.getLogger(__name__)

pd.set_option('future.no_silent_downcasting', True)

# Set current path
curpth = os.path.join(BASE_DIR, 'logics')

# Input and output file paths
input_files = {
    'skilling': os.path.join(curpth, "data","Input", "Centene Modified Roster-2.xlsm"),
    'target': os.path.join(curpth, "data",'constants','calculations.xlsx'),
    'vendor_template': os.path.join(curpth, "data","Input", "NTT_Capacity Roster Template.xlsx"),
    'combinations': os.path.join(curpth, "data",'constants',"combinations_2.xlsx")
}
output_file = os.path.join(curpth, "result.xlsx")

# Load input DataFrames
try:
    # skilling_df = pd.read_excel(input_files['skilling'], sheet_name="Skilling", dtype=str)
    # target_df = pd.read_excel(input_files['target'], sheet_name="Target_cph")
    # vendor_df = pd.read_excel(input_files['vendor_template'], sheet_name='Prod Team Roster', dtype=str)
    combinations_df = pd.read_excel(input_files['combinations'])
except Exception as e:
    logger.error(f"Failed to load input files: {e}")
    sys.exit(1)


# Load variables and months
req_vars_df = pd.read_excel(input_files['target'], sheet_name="Sheet1")
# req_months_df = pd.read_excel(input_files['target'], sheet_name="Sheet2")
occupancy = req_vars_df['Occupancy'].iloc[0]
shrinkage = req_vars_df['Shrinkage'].iloc[0]
workhours = req_vars_df['Work hours'].iloc[0]
# month_headers = req_months_df['Months'].tolist()
month_with_days = dict(zip(req_vars_df['months'], req_vars_df['No.of days occupancy']))

# Load combinations
combination_list = [eval(x) for x in combinations_df['combination'] if 'nan' not in x]

# Global dictionary for skill split counts
state_with_worktype_volume_dict = {}

# Helper functions
def get_value(row, month, filetype, df:pd.DataFrame=None, unnamed_count=None):
    if df is None or getattr(df, 'empty', True):
        return 0
    
    file_name = row[('Centene Capacity plan', 'Main LOB')]
    state = row[('Centene Capacity plan', 'State')]
    work_type = row[('Centene Capacity plan', 'Case type')]
    # file_paths = {
    #     'nonmmp': os.path.join(curpth, "data", 'constants',"medicare_medicaid_nonmmp", f"{file_name}.xlsx"),
    #     'mmp': os.path.join(curpth, "data", 'constants',"medicare_medicaid_mmp", f"{file_name}.xlsx"),
    #     'summary': os.path.join(curpth, "data", 'constants',"medicare_medicaid_summary", f"{file_name}-summary.xlsx")
    # }
    try:
        if filetype == 'medicare_medicaid_nonmmp':
            # df = pd.read_excel(file_paths['nonmmp'], header=[0, 1, 2])
            # df.columns = df.columns.map(lambda x: tuple(i if 'Unnamed' not in str(i) else '' for i in x))
            filtered_df = df[(df[('', '', 'State')] == state) & (df[('', '', 'Month')] == month)]
            if not filtered_df.empty:
                for col in filtered_df.columns:
                    if "WFM TO PROVIDE" in col[0].upper() and work_type in col:
                        return filtered_df[col].values[0]
            return 0
        elif filetype == 'medicare_medicaid_mmp':
            # df = pd.read_excel(file_paths['mmp'], header=[0, 1])
            filtered_df = df[(df[('State', 'State')] == state) & (df[('Month', 'Month')] == month)]
            if not filtered_df.empty:
                for col in filtered_df.columns:
                    if work_type == col[0]:
                        return filtered_df[col].values[0]
            return 0
        elif filetype == 'medicare_medicaid_summary':
            # df = pd.read_excel(file_paths['summary'], header=[0, 1, 2, 3])
            # df.columns = df.columns.map(lambda x: tuple(datetime.strptime(i, "%Y-%m-%d %H:%M:%S").strftime('%B') if ":" in i and "unnamed" not in i.lower() else i for i in x))
            filtered_df = df[df[(file_name, "Vendor Eligible Forecast (WFM)", "Work Type", "")] == work_type]
            if not filtered_df.empty:
                return filtered_df[(file_name, "Vendor Eligible Forecast (WFM)", month, "")].values[0]
            return 0
    except Exception as e:
        logging.warning(f"Error in get_value for {file_name}, {filetype}, {month}: {e}")
        return 0

class Calculations():
    def __init__(self) -> None:
        self.target_cph: pd.DataFrame = pd.DataFrame()
        self.month_data: pd.DataFrame = pd.DataFrame()
        self.occupancy: float
        self.shrinkage: float
        self.workhours: int
        self.month_with_days:dict[str, int]

        calculations = get_calculations_data()
        self.month_data = calculations.get("month_data", pd.DataFrame)
        self.target_cph = calculations.get("target_cph", pd.DataFrame)

        self.occupancy = self.month_data['Occupancy'].iloc[0] if not self.month_data.empty else 0.0
        self.shrinkage = self.month_data['Shrinkage'].iloc[0] if not self.month_data.empty else 0.0
        self.workhours = self.month_data['Work hours'].iloc[0] if not self.month_data.empty else 0


        # occupancy = req_vars_df['Occupancy'].iloc[0]
        # shrinkage = req_vars_df['Shrinkage'].iloc[0]
        # workhours = req_vars_df['Work hours'].iloc[0]
        # # month_headers = req_months_df['Months'].tolist()
        # month_with_days = dict(zip(req_vars_df['months'], req_vars_df['No.of days occupancy']))
        if not self.month_data.empty and 'months' in self.month_data.columns and 'No.of days occupancy' in self.month_data.columns:
            self.month_with_days = dict(zip(self.month_data['months'], self.month_data['No.of days occupancy']))
        else:
            self.month_with_days = {}


    def get_target_cph(self, row):
        lob = row[('Centene Capacity plan', 'Main LOB')]
        worktype = row[('Centene Capacity plan', 'Case type')]
        logger.debug(f"~~ ENTER get_target_cph: lob={lob!r}, worktype={worktype!r}")
        target_df = self.target_cph
        # filtered_target_df = self.target_cph[(self.target_cph['Case type'].str.lower() == worktype.lower()) & (self.target_cph['Main LOB'].str.strip() == lob.strip())]
        filtered_target_df = target_df[
            (target_df['Main LOB'].str.strip().str.lower() == lob.strip().lower()) &
            (target_df['Case type'].str.strip().str.lower() == worktype.strip().lower())
        ]
        # logger.debug(f"filtered target df head - {filtered_target_df.head()}")
        return filtered_target_df['Target CPH'].iloc[0] if not filtered_target_df.empty else 0
       


# def get_target_cph(row):
#     lob = row[('Centene Capacity plan', 'Main LOB')]
#     worktype = row[('Centene Capacity plan', 'Case type')]
#     logger.debug(f"~~ ENTER get_target_cph: lob={lob!r}, worktype={worktype!r}")
#     filtered_target_df = target_df[(target_df['Case type'].str.lower() == worktype.lower()) & (target_df['Main LOB'].str.strip() == lob.strip())]
#     return filtered_target_df['Target CPH'].iloc[0] if not filtered_target_df.empty else 0

def get_fte_required(row, month, calculations: Calculations):
    target_cph = row[('Centene Capacity plan', 'Target CPH')]
    month_value = row[('Client Forecast', month)]
    no_of_days = calculations.month_with_days[month]
    return month_value / (target_cph * calculations.workhours * calculations.occupancy * (1 - calculations.shrinkage) * no_of_days) if target_cph != 0 else 0

def get_temp_casetype(casetype):
    casetype = str(casetype)
    if not casetype or casetype == 'nan':
        return ''
    ct = casetype.split("-")[0].lower()
    return {'app': 'appeal', 'omn': 'omni'}.get(ct, ct)

# def get_skills_split_count(row, month, df):
#     global state_with_worktype_volume_dict
#     worktype = row[('Centene Capacity plan', 'Case type')]
#     state = row[('Centene Capacity plan', 'State')]
#     fte_required = row[('FTE Required', month)]
#     volume = {}
#     if f"{state}_{month}" not in state_with_worktype_volume_dict:
#         try:
#             df['State'] = df['State'].fillna('')
#             filtered_df = df if state == 'N/A' else df[df['State'].str.contains(state)]
#             work_types = sorted(filtered_df['NewWorkType'].tolist(), key=len, reverse=True)
#             for wt in work_types:
#                 for comb in combination_list:
#                     if len(list(comb)) > 1:
#                         if sorted(" ".join(list(comb))) == sorted(wt.strip()):
#                             volume[comb] = volume.get(comb, 0) + 1
#                     elif comb == (wt,):
#                         volume[comb] = volume.get(comb, 0) + 1
#             if volume:
#                 state_with_worktype_volume_dict[f"{state}_{month}"] = volume
#         except Exception as e:
#             logging.warning(f"Error in get_skills_split_count for {state}_{month}: {e}")
#     try:
#         current_bucket = state_with_worktype_volume_dict[f"{state}_{month}"]
#         available_fte = 0
#         if (worktype,) in current_bucket:
#             if current_bucket[(worktype,)] >= fte_required:
#                 state_with_worktype_volume_dict[f"{state}_{month}"][(worktype,)] -= fte_required
#                 return fte_required
#             else:
#                 available_fte = current_bucket[(worktype,)]
#                 state_with_worktype_volume_dict[f"{state}_{month}"][(worktype,)] = 0
#                 remaining_fte = fte_required - available_fte
#                 for k, v in current_bucket.items():
#                     if remaining_fte == 0:
#                         return fte_required
#                     if len(k) > 1 and worktype in k:
#                         if v > remaining_fte:
#                             available_fte += remaining_fte
#                             state_with_worktype_volume_dict[f"{state}_{month}"][k] -= remaining_fte
#                             remaining_fte = 0
#                         else:
#                             available_fte += v
#                             state_with_worktype_volume_dict[f"{state}_{month}"][k] = 0
#                             remaining_fte -= v
#                 return available_fte
#         else:
#             remaining_fte = fte_required
#             for k, v in current_bucket.items():
#                 if remaining_fte == 0:
#                     return fte_required
#                 if len(k) > 1 and worktype in k:
#                     if v > remaining_fte:
#                         available_fte += remaining_fte
#                         state_with_worktype_volume_dict[f"{state}_{month}"][k] -= remaining_fte
#                         remaining_fte = 0
#                     else:
#                         available_fte += v
#                         state_with_worktype_volume_dict[f"{state}_{month}"][k] = 0
#                         remaining_fte -= v
#             return available_fte
#     except KeyError:
#         return 0

def get_skills_split_count(row, month, df):
    # pdb.set_trace()
    global state_with_worktype_volume_dict
    platform = row[('Centene Capacity plan', 'Main LOB')]
    platform= str(platform).split(" ")[0]
    worktype = row[('Centene Capacity plan', 'Case type')]
    state = row[('Centene Capacity plan', 'State')]
    fte_required = row[('FTE Required', month)]
    key = f"{platform}_{state}_{month}"
    
    logging.debug(f"~~ ENTER get_skills_split_count: state={state!r}, month={month!r}, worktype={worktype!r}, fte_required={fte_required}")
    # pdb.set_trace()
    # initialize bucket if missing
    if key not in state_with_worktype_volume_dict:
        try:
            # fill missing
            df_copy = df.copy()
            df_copy['State'] = df_copy['State'].fillna('')
            if state == 'N/A':
                filtered_df = df_copy
            else:
                filtered_df = df_copy[df_copy['State'].str.contains(state, na=False)]
            logging.debug(f"    filtered_df.shape = {filtered_df.shape}")
            
            volume = {}
            # count occurrences by your combination logic
            work_types = sorted(filtered_df['NewWorkType'].tolist(), key=len, reverse=True)
            logging.debug(f"    vendor NewWorkType list (sample 10): {work_types[:10]}")
            logging.debug(f"    vendor NewWorkType list (sample 10): {work_types[:-11:-1]}")
            
            for wt in work_types:
                for comb in combination_list:
                    if len(comb) > 1:
                        if sorted(" ".join(comb)) == sorted(wt.strip()):
                            volume[comb] = volume.get(comb, 0) + 1
                    elif comb == (wt,):
                        volume[comb] = volume.get(comb, 0) + 1
            logging.debug(f"    built volume buckets: {volume}")
            state_with_worktype_volume_dict[key] = volume
        except Exception as e:
            logging.warning(f"    ERROR initializing bucket for {key}: {e}")
            state_with_worktype_volume_dict[key] = {}
    
    bucket = state_with_worktype_volume_dict.get(key, {})
    logging.debug(f"    existing bucket for {key}: {bucket}")
    
    # now allocate from bucket
    available = 0.0
    remaining = fte_required
    
    # first try the exact single-type slot
    single = (worktype,)
    if single in bucket:
        have = bucket[single]
        take = min(have, remaining)
        bucket[single] -= take
        available += take
        remaining  -= take
        logging.debug(f"    took {take} from single bucket {single}, now bucket={bucket[single]}, remaining={remaining}")
    
    # then try multi-type slots that include our worktype
    if remaining > 0:
        for comb, cnt in list(bucket.items()):
            if remaining <= 0:
                break
            if len(comb) > 1 and worktype in comb and cnt > 0:
                take = min(cnt, remaining)
                bucket[comb] -= take
                available   += take
                remaining   -= take
                logging.debug(f"    took {take} from combo bucket {comb}, now bucket={bucket[comb]}, remaining={remaining}")
    
    logging.debug(f"~~ EXIT get_skills_split_count returning {available} (needed {fte_required}) for key={key}")
    return available

def get_capacity(row, month):
    target_cph = row[('Centene Capacity plan', 'Target CPH')]
    fte_available = row[('FTE Avail', month)]  # Corrected key
    no_of_days = month_with_days.get(month, 0)
    try:
        logging.debug(f"FTE Avail for {month}: {fte_available}")
        return target_cph * fte_available * (1 - shrinkage) * no_of_days * workhours
    except Exception as e:
        logging.error(f"Error in get_capacity for {month}: {e}")
        return 0

# def filter_vendor_df(file_name, vendor_df):
#     platform = file_name.split(" ")[0]
#     market = file_name.split(" ")[1].split("-")[0] if "-summary" in file_name.lower() else file_name.split(" ")[0]
#     location = 'Domestic' if 'domestic' in file_name.lower() else 'Global'
#     filtered_df = vendor_df[
#         (vendor_df['PartofProduction'].isin(['Production', 'Ramp'])) &
#         (vendor_df['Location'] == location) &
#         (vendor_df['BeelineTitle'] == 'Claims Analyst') &
#         (vendor_df['PrimaryPlatform'] == platform) &
#         (vendor_df['PrimaryMarket'].str.lower() == market.lower())
#     ]
#     filtered_df.columns = filtered_df.columns.str.replace("\n", "").str.strip()
#     return filtered_df

def filter_vendor_df(file_name, vendor_df):
    platform = file_name.split(" ")[0]
    market =  file_name.split(" ")[0]
    location = 'Domestic' if 'domestic' in file_name.lower() else 'Global'

    logging.debug(f"--- filter_vendor_df ---\n"
                  f" file_name = {file_name!r}\n"
                  f" platform = {platform!r}\n"
                  f" market   = {market!r}\n"
                  f" location = {location!r}\n"
                  f" vendor_df BEFORE filter: {vendor_df.shape}")

    # filtered_df = vendor_df[
    #     (vendor_df['PartofProduction'].isin(['Production', 'Ramp'])) &
    #     (vendor_df['Location'] == location) &
    #     (vendor_df['BeelineTitle'] == 'Claims Analyst') &
    #     (vendor_df['PrimaryPlatform'] == platform) &
    #     (vendor_df['PrimaryMarket'].str.lower() == market.lower())
    # ]
    #removed Primary market value as it goes empty df after this filter 07242025 
    filtered_df = vendor_df[
        (vendor_df['PartofProduction'].isin(['Production', 'Ramp'])) &
        (vendor_df['Location'].str.lower() == location.lower()) &
        (vendor_df['BeelineTitle'] == 'Claims Analyst') &
        (vendor_df['PrimaryPlatform'].str.lower() == platform.lower())
    ]

    logging.debug(f" filtered_df AFTER filter: {filtered_df.shape}")
    if filtered_df.empty:
        logging.warning(f"No vendors found for {file_name} with "
                        f"Platform={platform}, Market={market}, Location={location}")

    filtered_df.columns = filtered_df.columns.str.replace("\n", "").str.strip()
    return filtered_df

def initialize_output_excel(month_headers:List[str]):
    wb = Workbook()
    ws = wb.active
    logger.debug(f"input month headers: {month_headers}")
    ws.title = "Capacity plan"
    main_headers = ["Centene Capacity plan", "Client Forecast", "FTE Required", "FTE Avail", "Capacity"]
    capacity_plan_headers = ["Main LOB", "State", "Case type", "Call Type ID", "Target CPH"]
    columns = capacity_plan_headers + month_headers * 4
    ws.merge_cells("A1:E1")
    ws.merge_cells("F1:K1")
    ws.merge_cells("L1:Q1")
    ws.merge_cells("R1:W1")
    ws.merge_cells("X1:AC1")
    ws["A1"] = "Centene Capacity plan"
    ws["F1"] = "Client Forecast"
    ws["L1"] = "FTE Required"
    ws["R1"] = "FTE Avail"
    ws["X1"] = "Capacity"
    header_font = Font(bold=True)
    header_alignment = Alignment(horizontal="center", vertical="center")
    for col in range(1, 32):
        ws.cell(row=1, column=col).font = header_font
        ws.cell(row=1, column=col).alignment = header_alignment
    for col, header in enumerate(columns, start=1):
        ws.cell(row=2, column=col, value=header).font = header_font
        ws.cell(row=2, column=col).alignment = header_alignment
    ws.auto_filter.ref = f"A2:{ws.cell(row=2, column=len(columns)).coordinate}"
    wb.save(output_file)

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

def get_nonmmp_columns(df:pd.DataFrame) -> List[str]:
    """
    Returns a list of unique third-level column names 
    from a multi-indexed DataFrame, where:
    - First-level column contains 'Forecast - Volume'
    - Third-level column does not contain 'Total'
    """
    # Ensure we are working with MultiIndex columns
    if not isinstance(df.columns, pd.MultiIndex):
        raise ValueError("DataFrame must have MultiIndex columns (3 levels).")
    
    # Filter columns where first level contains 'Forecast - Volume'
    filtered = [col for col in df.columns if "Forecast - Volume" in str(col[0])]
    
    # Extract the third-level names
    third_level_names = [col[2] for col in filtered if "Total" not in str(col[2])]
    
    # Return unique names as a list
    return sorted(set(third_level_names))


def process_files(data_month: str, data_year: int, forecast_file_uploaded_by: str, forecast_filename: str):
    """
    Simulates logic after forecast file upload and updates the processed forecast data.
    """
    start_time = datetime.now()
    logging.info("Starting file processing")
    global state_with_worktype_volume_dict
    state_with_worktype_volume_dict = {}
    skilling_df = get_latest_or_requested_dataframe('skilling', data_month, data_year)
    vendor_df = get_latest_or_requested_dataframe('prod_team_roster', data_month, data_year)
    month_headers = get_forecast_months_list(data_month, data_year, forecast_filename)
    calculations = Calculations()
    initialize_output_excel(month_headers)
    output_dfs = []
    file_types = get_all_model_dataframes_dict(data_month, data_year)
    directories = {
        'mmp': os.path.join(curpth, "data", 'constants',"medicare_medicaid_mmp"),
        'nonmmp': os.path.join(curpth,"data", 'constants', "medicare_medicaid_nonmmp"),
        'summary': os.path.join(curpth, "data", 'constants',"medicare_medicaid_summary")
    }
    
    for file_type, directory in file_types.items():
        for file_name, df in directory.items():
            # if not file_name.endswith('.xlsx'):
            logger.info(f"Processing {file_type} file: {file_name}")
            vendor_filtered_df = filter_vendor_df(file_name, vendor_df)
            client_names, states, work_types = [], [], []
            # logger.debug(f"Column values: ")
            # for col in df.columns:
            #     logger.debug(f"column value ---- {col}")
            if file_type == 'medicare_medicaid_mmp':
                try:
                    # work_types = [str(wt).strip() for wt in df.columns.get_level_values(0)[6:15] if str(wt).strip()]
                    work_types = get_columns_between_column_names(df,0,'Mo St', 'Year')
                    logging.info(f"Extracted work_types: {work_types}, length: {len(work_types)}, top 5 worktypes: {work_types[:5]}")
                    states = list(set(s for s in df[('State', 'State')].dropna() if s != 0 and isinstance(s, str)))
                    logging.info(f"Extracted states: {states}, length: {len(states)}")
                    if not work_types or not states:
                        logging.warning(f"No valid work types or states for {file_name}. Skipping.")
                        continue
                    total_rows = len(states) * len(work_types)
                    states_expanded = [s for s in states for _ in work_types]
                    work_types_expanded = work_types * len(states)
                    client_names = [file_name] * total_rows
                    logging.info(f"Expected rows: {total_rows}, states: {len(states_expanded)}, work_types: {len(work_types_expanded)}, client_names: {len(client_names)}")
                    print("!!!!!!!!!!!!")
                    print(work_types)
                    print(states_expanded)
                    print(len(states))
                    print("!!!!!!!!!!!!")
                    print(total_rows)
                    print(states_expanded)
                    print(work_types_expanded)
                except Exception as e:
                    logging.error(f"Error reading MMP file {file_name}: {e}")
                    continue

            elif file_type == 'medicare_medicaid_nonmmp':
                try:
                    df.columns = df.columns.map(lambda x: tuple(i if 'Unnamed' not in str(i) else '' for i in x))
                    # third_level_headers = [col[2] for col in df.columns]
                    # work_types = []
                    # index = 5
                    # while index < len(third_level_headers):
                    #     work_types.extend([str(third_level_headers[index]).strip(), str(third_level_headers[index + 1]).strip()] if index + 1 < len(third_level_headers) else [str(third_level_headers[index]).strip()])
                    #     index += 11
                    
                    work_types = get_nonmmp_columns(df)
                    logging.info(f"Extracted work_types: {work_types}, length: {len(work_types)}")
                    states = list(set(df[('', '', 'State')].dropna()))
                    logging.info(f"Extracted states: {states}, length: {len(states)}")
                    total_rows = len(states) * len(work_types)
                    states_expanded = [s for s in states for _ in work_types]
                    work_types_expanded = work_types * len(states)
                    client_names = [file_name] * total_rows
                    logging.info(f"Expected rows: {total_rows}, states: {len(states_expanded)}, work_types: {len(work_types_expanded)}, client_names: {len(client_names)}")
                except Exception as e:
                    logging.error(f"Error reading non-MMP file {file_name}: {e}")
                    continue

            elif file_type == 'medicare_medicaid_summary' and 'mmp' not in file_name.lower():
                try:
                    if df.empty:
                        logging.warning(f"Empty DataFrame for {file_name}. Skipping.")
                        continue
                    logging.info(f"DataFrame shape for {file_name}: {df.shape}")
                    df.columns = df.columns.map(lambda x: tuple(i if 'Unnamed' not in str(i) else '' for i in x))
                    # df.columns = df.columns.sort_values()
                    first_col = file_name.split("-summary")[0]
                    logging.info(f"Summary file columns: {df.columns.tolist()}")
                    work_type_col = None
                    for col in df.columns:
                        if col[2].lower() in ['work type', 'worktype', 'case type']:
                            work_type_col = col
                            break
                    if work_type_col:
                        try:
                            work_type_values = list(df[work_type_col].dropna())
                            logging.info(f"Work Type column values: {work_type_values}")
                        except Exception as e:
                            logging.warning(f"Failed to log Work Type values for {file_name}: {e}")
                            work_type_values = []
                        work_types = [str(wkt) for wkt in df[work_type_col].fillna('') if str(wkt).lower() != "total" and str(wkt).strip()]
                    else:
                        logging.warning(f"No 'Work Type' column found in {file_name}. Available columns: {df.columns.tolist()}")
                        continue
                    logging.info(f"Extracted work_types: {work_types}, length: {len(work_types)}")
                    states = ["N/A"] * len(work_types)
                    client_names = [first_col] * len(work_types)
                    total_rows = len(work_types)
                    states_expanded = states
                    work_types_expanded = work_types
                    logging.info(f"Expected rows: {total_rows}, states: {len(states_expanded)}, work_types: {len(work_types_expanded)}, client_names: {len(client_names)}")
                except Exception as e:
                    logging.error(f"Error reading summary file {file_name}: {e}")
                    continue

            if not work_types_expanded:
                logging.warning(f"No valid work types found for {file_name}. Skipping.")
                continue

            # Initialize output_df with correct number of rows
            column_template = pd.read_excel(output_file, header=[0, 1]).columns
            output_df = pd.DataFrame(index=range(total_rows), columns=column_template)
            try:
                output_df[('Centene Capacity plan', 'Main LOB')] = client_names
                output_df[('Centene Capacity plan', 'State')] = states_expanded
                output_df[('Centene Capacity plan', 'Case type')] = work_types_expanded
                output_df[('Centene Capacity plan', 'temp_Case type')] = output_df[('Centene Capacity plan', 'Case type')].apply(get_temp_casetype)
                output_df[('Centene Capacity plan', 'Call Type ID')] = output_df[('Centene Capacity plan', 'Main LOB')].astype(str) + output_df[('Centene Capacity plan', 'temp_Case type')].astype(str)
                output_df.drop(columns=[('Centene Capacity plan', 'temp_Case type')], inplace=True)
            except ValueError as e:
                logging.error(f"Length mismatch in {file_name}: {e}")
                logging.info(f"client_names: {len(client_names)}, states: {len(states_expanded)}, work_types: {len(work_types_expanded)}")
                continue
            for month in month_headers:
                if file_type == 'medicare_medicaid_mmp':
                    output_df[('Client Forecast', month)] = output_df.apply(lambda row: get_value(row, month, 'medicare_medicaid_mmp', df), axis=1)
                elif file_type == 'medicare_medicaid_nonmmp':
                    output_df[('Client Forecast', month)] = output_df.apply(lambda row: get_value(row, month, 'medicare_medicaid_nonmmp', df), axis=1)
                elif file_type == 'medicare_medicaid_summary':
                    output_df[('Client Forecast', month)] = output_df.apply(lambda row: get_value(row, month, 'medicare_medicaid_summary', df, 3 + month_headers.index(month)), axis=1)

            output_df[('Centene Capacity plan', 'Target CPH')] = output_df.apply(calculations.get_target_cph, axis=1)
            for month in month_headers:
                output_df[('FTE Required', month)] = output_df.apply(lambda row: get_fte_required(row, month, calculations), axis=1)
                output_df[('FTE Required', month)] = output_df[('FTE Required', month)].apply(lambda x: 0.5 if 0 < x < 0.5 else x)
            output_df = output_df.fillna(0).infer_objects(copy=False)
            output_df[output_df.select_dtypes(include=['number']).columns] = output_df.select_dtypes(include=['number']).round().astype(int)

            output_df = output_df.apply(lambda row: process_row_level(row, month_headers,vendor_filtered_df), axis=1)
            for month in month_headers:
                output_df[('Capacity', month)] = output_df.apply(lambda row: get_capacity(row, month), axis=1)
            output_df = output_df.fillna(0).infer_objects(copy=False)
            output_df[output_df.select_dtypes(include=['number']).columns] = output_df.select_dtypes(include=['number']).round().astype(int)

            output_dfs.append(output_df)


    # for file_type, directory in directories.items():
    #     for file_name in [f.split(".xlsx")[0] for f in os.listdir(directory) if f.endswith(".xlsx")]:
    #         logging.info(f"Processing {file_type} file: {file_name}")
    #         vendor_filtered_df = filter_vendor_df(file_name, vendor_df)
    #         client_names, states, work_types = [], [], []

    #         if file_type == 'mmp' and 'summary' not in file_name.lower():
    #             try:
    #                 df = pd.read_excel(os.path.join(directory, f"{file_name}.xlsx"), header=[0, 1])
    #                 work_types = [str(wt).strip() for wt in df.columns.get_level_values(0)[6:15] if str(wt).strip()]
    #                 logging.info(f"Extracted work_types: {work_types}, length: {len(work_types)}")
    #                 states = list(set(s for s in df[('State', 'State')].dropna() if s != 0 and isinstance(s, str)))
    #                 logging.info(f"Extracted states: {states}, length: {len(states)}")
    #                 if not work_types or not states:
    #                     logging.warning(f"No valid work types or states for {file_name}. Skipping.")
    #                     continue
    #                 total_rows = len(states) * len(work_types)
    #                 states_expanded = [s for s in states for _ in work_types]
    #                 work_types_expanded = work_types * len(states)
    #                 client_names = [file_name] * total_rows
    #                 logging.info(f"Expected rows: {total_rows}, states: {len(states_expanded)}, work_types: {len(work_types_expanded)}, client_names: {len(client_names)}")
    #                 print("!!!!!!!!!!!!")
    #                 print(work_types)
    #                 print(states_expanded)
    #                 print(len(states))
    #                 print("!!!!!!!!!!!!")
    #                 print(total_rows)
    #                 print(states_expanded)
    #                 print(work_types_expanded)
    #             except Exception as e:
    #                 logging.error(f"Error reading MMP file {file_name}: {e}")
    #                 continue

    #         elif file_type == 'nonmmp' and 'summary' not in file_name.lower():
    #             try:
    #                 df = pd.read_excel(os.path.join(directory, f"{file_name}.xlsx"), header=[0, 1, 2])
    #                 df.columns = df.columns.map(lambda x: tuple(i if 'Unnamed' not in str(i) else '' for i in x))
    #                 third_level_headers = [col[2] for col in df.columns]
    #                 work_types = []
    #                 index = 5
    #                 while index < len(third_level_headers):
    #                     work_types.extend([str(third_level_headers[index]).strip(), str(third_level_headers[index + 1]).strip()] if index + 1 < len(third_level_headers) else [str(third_level_headers[index]).strip()])
    #                     index += 11
    #                 logging.info(f"Extracted work_types: {work_types}, length: {len(work_types)}")
    #                 states = list(set(df[('', '', 'State')].dropna()))
    #                 logging.info(f"Extracted states: {states}, length: {len(states)}")
    #                 total_rows = len(states) * len(work_types)
    #                 states_expanded = [s for s in states for _ in work_types]
    #                 work_types_expanded = work_types * len(states)
    #                 client_names = [file_name] * total_rows
    #                 logging.info(f"Expected rows: {total_rows}, states: {len(states_expanded)}, work_types: {len(work_types_expanded)}, client_names: {len(client_names)}")
    #             except Exception as e:
    #                 logging.error(f"Error reading non-MMP file {file_name}: {e}")
    #                 continue

    #         elif file_type == 'summary' and 'mmp' not in file_name.lower():
    #             try:
    #                 df = pd.read_excel(os.path.join(directory, f"{file_name}.xlsx"), header=[0, 1, 2, 3])
    #                 if df.empty:
    #                     logging.warning(f"Empty DataFrame for {file_name}. Skipping.")
    #                     continue
    #                 logging.info(f"DataFrame shape for {file_name}: {df.shape}")
    #                 df.columns = df.columns.map(lambda x: tuple(i if 'Unnamed' not in str(i) else '' for i in x))
    #                 df.columns = df.columns.sort_values()
    #                 first_col = file_name.split("-summary")[0]
    #                 logging.info(f"Summary file columns: {df.columns.tolist()}")
    #                 work_type_col = None
    #                 for col in df.columns:
    #                     if col[2].lower() in ['work type', 'worktype', 'case type']:
    #                         work_type_col = col
    #                         break
    #                 if work_type_col:
    #                     try:
    #                         work_type_values = list(df[work_type_col].dropna())
    #                         logging.info(f"Work Type column values: {work_type_values}")
    #                     except Exception as e:
    #                         logging.warning(f"Failed to log Work Type values for {file_name}: {e}")
    #                         work_type_values = []
    #                     work_types = [str(wkt) for wkt in df[work_type_col].fillna('') if str(wkt).lower() != "total" and str(wkt).strip()]
    #                 else:
    #                     logging.warning(f"No 'Work Type' column found in {file_name}. Available columns: {df.columns.tolist()}")
    #                     continue
    #                 logging.info(f"Extracted work_types: {work_types}, length: {len(work_types)}")
    #                 states = ["N/A"] * len(work_types)
    #                 client_names = [first_col] * len(work_types)
    #                 total_rows = len(work_types)
    #                 states_expanded = states
    #                 work_types_expanded = work_types
    #                 logging.info(f"Expected rows: {total_rows}, states: {len(states_expanded)}, work_types: {len(work_types_expanded)}, client_names: {len(client_names)}")
    #             except Exception as e:
    #                 logging.error(f"Error reading summary file {file_name}: {e}")
    #                 continue

    #         if not work_types_expanded:
    #             logging.warning(f"No valid work types found for {file_name}. Skipping.")
    #             continue

    #         # Initialize output_df with correct number of rows
    #         column_template = pd.read_excel(output_file, header=[0, 1]).columns
    #         output_df = pd.DataFrame(index=range(total_rows), columns=column_template)
    #         try:
    #             output_df[('Centene Capacity plan', 'Main LOB')] = client_names
    #             output_df[('Centene Capacity plan', 'State')] = states_expanded
    #             output_df[('Centene Capacity plan', 'Case type')] = work_types_expanded
    #             output_df[('Centene Capacity plan', 'temp_Case type')] = output_df[('Centene Capacity plan', 'Case type')].apply(get_temp_casetype)
    #             output_df[('Centene Capacity plan', 'Call Type ID')] = output_df[('Centene Capacity plan', 'Main LOB')].astype(str) + output_df[('Centene Capacity plan', 'temp_Case type')].astype(str)
    #             output_df.drop(columns=[('Centene Capacity plan', 'temp_Case type')], inplace=True)
    #         except ValueError as e:
    #             logging.error(f"Length mismatch in {file_name}: {e}")
    #             logging.info(f"client_names: {len(client_names)}, states: {len(states_expanded)}, work_types: {len(work_types_expanded)}")
    #             continue
    #         for month in month_headers:
    #             if file_type == 'mmp':
    #                 output_df[('Client Forecast', month)] = output_df.apply(lambda row: get_value(row, month, 'mmp'), axis=1)
    #             elif file_type == 'nonmmp':
    #                 output_df[('Client Forecast', month)] = output_df.apply(lambda row: get_value(row, month, 'nonmmp'), axis=1)
    #             elif file_type == 'summary':
    #                 output_df[('Client Forecast', month)] = output_df.apply(lambda row: get_value(row, month, 'summary', 3 + month_headers.index(month)), axis=1)

    #         output_df[('Centene Capacity plan', 'Target CPH')] = output_df.apply(get_target_cph, axis=1)
    #         for month in month_headers:
    #             output_df[('FTE Required', month)] = output_df.apply(lambda row: get_fte_required(row, month), axis=1)
    #             output_df[('FTE Required', month)] = output_df[('FTE Required', month)].apply(lambda x: 0.5 if 0 < x < 0.5 else x)
    #         output_df = output_df.fillna(0).infer_objects(copy=False)
    #         output_df[output_df.select_dtypes(include=['number']).columns] = output_df.select_dtypes(include=['number']).round().astype(int)

    #         output_df = output_df.apply(lambda row: process_row_level(row, vendor_filtered_df), axis=1)
    #         for month in month_headers:
    #             output_df[('Capacity', month)] = output_df.apply(lambda row: get_capacity(row, month), axis=1)
    #         output_df = output_df.fillna(0).infer_objects(copy=False)
    #         output_df[output_df.select_dtypes(include=['number']).columns] = output_df.select_dtypes(include=['number']).round().astype(int)

    #         output_dfs.append(output_df)

    if output_dfs:
        logging.debug(f"final total output_dfs - {len(output_dfs)}")
        consolidated_df = pd.concat(output_dfs, ignore_index=True)
        preprocessor = PreProcessing("forecast")
        mod_consolitated_df = preprocessor.preprocess_forecast_df(consolidated_df.copy())
        logging.debug(f"consolidated df to be exported as excel - {consolidated_df.head()}")
        logging.debug(f"shape - {consolidated_df.shape}")
        update_forecast_data(mod_consolitated_df, data_month, data_year, forecast_file_uploaded_by, forecast_filename)
        logging.info("Forecast data updated successfully.")
        update_summary_data(data_month, data_year)
        consolidated_df.to_excel(output_file)
        logging.info(f"Saved consolidated output to {output_file}")
    else:
        logging.error("No valid DataFrames generated. Check input files.")

    end_time = datetime.now()
    logging.info(f"Processing completed. Total time: {end_time - start_time}")

def process_row_level(row, month_headers, vendor_df):
    for month in month_headers:
        row[('FTE Avail', month)] = get_skills_split_count(row, month, vendor_df)
        logging.debug(f"FTE Avail for {month}: {row[('FTE Avail', month)]}")
    return row

if __name__ == "__main__":
    # pass
    process_files('March', 2025, 'Makzoom Shah', 'NTT Forecast - v4_Capacity and HC_March_2025.xlsx')