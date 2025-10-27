# import sys
# import os
# sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from typing import Iterable, Dict, Mapping, MutableMapping, List
from code.logics.core_utils import (
    get_model_or_all_models,
    PreProcessing, 
    CoreUtils, 
    PostProcessing
)
import pandas as pd
import logging
import re
import numpy as np

from code.settings import  (
    MODE,
    SQLITE_DATABASE_URL, 
    MSSQL_DATABASE_URL,
    BASE_DIR
)

import os
from io import BytesIO

from code.logics.db import RawData, ForecastModel, UploadDataTimeDetails, ForecastMonthsModel
import calendar

if MODE.upper() == "DEBUG":
    DATABASE_URL = SQLITE_DATABASE_URL
elif MODE.upper() == "PRODUCTION":
    DATABASE_URL = MSSQL_DATABASE_URL
else:
    raise ValueError("Invalid MODE specified in config.")

# Step 2: Initialize the CoreUtils instance with final DB URL
core_utils = CoreUtils(DATABASE_URL)

logger = logging.getLogger(__name__)

def get_processed_dataframe(file_id: str, month: str = None, year: int = None) -> pd.DataFrame:
    """
    Returns a processed DataFrame similar to the download endpoint,
    based on file_id, month, and year.

    Raises:
        ValueError: If file_id is invalid, no data found, or missing column mappings
        Exception: For database connection errors or DataFrame processing errors
    """
    try:
        # Get the model based on file_id
        Model = get_model_or_all_models(file_id)

        if not Model:
            raise ValueError(f"Invalid file_id provided: {file_id}")

        # Get the columns from PreProcessing
        try:
            preprocessor = PreProcessing(file_id)
            select_columns = preprocessor.MAPPING.get(file_id)
        except Exception as e:
            logger.error(f"Error initializing PreProcessing for {file_id}: {e}")
            raise ValueError(f"Failed to get column mapping for file_id: {file_id}") from e

        if not select_columns:
            raise ValueError(f"No column mapping found for file_id: {file_id}")

        # Get total records with database error handling
        try:
            db_manager = core_utils.get_db_manager(Model, limit=1, skip=0)
            total = db_manager.get_totals()
        except Exception as e:
            logger.error(f"Database error while getting totals for {file_id}: {e}", exc_info=True)
            raise ValueError(f"Database error: Could not retrieve total records for file_id: {file_id}") from e

        if total is None:
            raise ValueError(f"Could not retrieve total records for file_id: {file_id}")
        if total == 0:
            raise ValueError(f"No records found for file_id: {file_id}")

        # Fetch complete data for the given file_id, month/year
        try:
            db_manager = core_utils.get_db_manager(Model, limit=total, skip=0, select_columns=select_columns)
            df = db_manager.download_db(month, year)
        except Exception as e:
            logger.error(f"Database error while downloading data for {file_id} (month={month}, year={year}): {e}", exc_info=True)
            raise ValueError(f"Database error: Failed to download data for {file_id}") from e

        if df is None or df.empty:
            logger.info(f"No data found for file_id: {file_id} with month: {month} and year: {year}")
            return pd.DataFrame()

        # Post-process columns
        try:
            post_processor = PostProcessing(core_utils)
        except Exception as e:
            logger.error(f"Error initializing PostProcessing: {e}")
            raise ValueError(f"Failed to initialize post-processing for {file_id}") from e

        if file_id == 'forecast':
            try:
                # Get label mappings if forecast
                db_manager_forecast = core_utils.get_db_manager(Model, limit=1, skip=0)
                forecast_data = db_manager_forecast.read_db(month, year)
                mappings = [list(pair) for pair in PostProcessing(core_utils=core_utils).MAPPING[file_id]]

                if 'records' in forecast_data and len(forecast_data['records']) == 1:
                    file_name = forecast_data['records'][0].get('UploadedFile', '')
                    db_manager_months = core_utils.get_db_manager(ForecastMonthsModel, limit=1, skip=0)
                    months_data = db_manager_months.search_db(['UploadedFile'], [file_name])

                    if 'records' in months_data and len(months_data['records']) == 1:
                        month_data = months_data['records'][0]

                        for i, (group, key) in enumerate(mappings):
                            if key in month_data:
                                mappings[i][1] = month_data[key]

                df.columns = pd.MultiIndex.from_tuples([tuple(pair) for pair in mappings])
            except Exception as e:
                logger.error(f"Error processing forecast column mappings: {e}", exc_info=True)
                raise ValueError(f"Failed to process forecast column mappings") from e
        else:
            try:
                df.columns = post_processor.MAPPING[file_id]
            except Exception as e:
                logger.error(f"Error applying column mappings for {file_id}: {e}")
                raise ValueError(f"Failed to apply column mappings for {file_id}") from e

        return df

    except ValueError:
        # Re-raise ValueError as-is (already has descriptive message)
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_processed_dataframe for {file_id}: {e}", exc_info=True)
        raise ValueError(f"Unexpected error while processing dataframe for {file_id}: {str(e)}") from e

def get_forecast_months_list(month:str, year:int, filename:str = None) -> list[str]:
    """
    retuns six forecast months in a list e.g, ['March', 'April', 'May', 'June', 'July', 'August']
    Argumnets:
        month: str -> Complete month name like March, April, etc
        year: int -> year in YYYY format like 2025
    """
    months = []
    try:
        db_manager = core_utils.get_db_manager(ForecastModel)
        months = db_manager.get_forecast_months_list(month, year, filename)
        # months = [month for month in months if month]  # Filter out None or empty strings
    except Exception as e:
        logger.error(f"Error : {e}")
    return months


def construct_multiindex_df(
    file_path: str,
    header_rows: tuple[int, int],
    data_rows: tuple[int, int],
    col_range: tuple[int, int],
    header_ffill_rows: int
) -> pd.DataFrame:
    """
    Generic function to construct a DataFrame with MultiIndex columns from an Excel file.
    Args:
        file_path: Path to the Excel file.
        header_rows: (start, end) tuple for header rows.
        data_rows: (start, end) tuple for data rows.
        col_range: (start, end) tuple for column slice.
        header_ffill_rows: Number of header rows to forward fill.
    Returns:
        pd.DataFrame with MultiIndex columns.
    """
    raw = pd.read_excel(file_path, header=None)
    if raw.empty:
        return pd.DataFrame()
    header_block = raw.iloc[header_rows[0]:header_rows[1], col_range[0]:col_range[1]]
    data_block = raw.iloc[data_rows[0]:data_rows[1], col_range[0]:col_range[1]]

    header_clean = header_block.copy()
    if header_ffill_rows > 0:
        header_clean.iloc[0:header_ffill_rows] = header_clean.iloc[0:header_ffill_rows].ffill(axis=1).fillna("").astype(str)
    header_clean.iloc[header_ffill_rows] = header_clean.iloc[header_ffill_rows].fillna("")

    columns = pd.MultiIndex.from_arrays(header_clean.values)
    df = pd.DataFrame(data_block.values, columns=columns).reset_index(drop=True)
    return df

def construct_grouped_summary_df(file_path: str) -> pd.DataFrame:
    # For grouped summary: header rows 0:4, data rows 5:end, columns 1:36, ffill first 3 header rows
    return construct_multiindex_df(
        file_path,
        header_rows=(0, 4),
        data_rows=(5, None),
        col_range=(1, 36),
        header_ffill_rows=3
    )

def construct_nonmmp_df(file_path: str) -> pd.DataFrame:
    # For nonmmp: header rows 0:3, data rows 4:end, columns 1:60, ffill first 2 header rows
    return construct_multiindex_df(
        file_path,
        header_rows=(0, 3),
        data_rows=(4, None),
        col_range=(1, 60),
        header_ffill_rows=2
    )

def construct_mmp_df(file_path: str) -> pd.DataFrame:
    # For nonmmp: header rows 0:3, data rows 4:end, columns 1:60, ffill first 2 header rows
    return construct_multiindex_df(
        file_path,
        header_rows=(0, 2),
        data_rows=(3, None),
        col_range=(1, 61),
        header_ffill_rows=1
    )


def get_latest_or_requested_dataframe(file_id: str, month: str = None, year: int = None) -> pd.DataFrame:
    """
    Returns processed DataFrame for given file_id, month, and year.
    If not available, automatically falls back to the most recent (latest) data.
    Returns empty DataFrame only if no records exist at all for the model.
    """

    try:
        # Try fetching using provided month/year
        df = get_processed_dataframe(file_id, month, year)
        if not df.empty:
            logger.info(f"Returned requested data for {file_id} - {month} {year}")
            return df
    except ValueError as ve:
        logger.warning(f"Requested data not found: {ve}") 

    # Step 2: Fallback to latest available data
    try:
        Model = get_model_or_all_models(file_id)
        db_manager = core_utils.get_db_manager(Model, limit=1, skip=0)
        latest_row = db_manager.get_latest_month_year()
        
        if not latest_row:
            logger.warning(f"No historical data found for {file_id}")
            return pd.DataFrame()

        latest_month = latest_row['Month']
        latest_year = latest_row['Year']

        logger.info(f"Falling back to latest data for {file_id}: {latest_month} {latest_year}")
        df = get_processed_dataframe(file_id, latest_month, latest_year)
        return df

    except Exception as e:
        logger.error(f"Error while fetching latest data for {file_id}: {e}")
        return pd.DataFrame()

def get_summary_data_by_summary_type(month: str, year: int, summary_type:str) -> pd.DataFrame:
    """ 
        returns the corresponding dataframe of given summary type and month details
        Args:
            month:  str => like "January", "February" , ...
            year: int => yyyy format like 2025
            summary_type: str => summary types ["Amisys Marketplace","Amisys Medicare","Amisys Projects- Domestic","Amisys Projects- Global","Facets Medicaid","Facets Medicare","OIC Volumes","Xcelys Medicaid (Domestic)","Xcelys Medicaid (Global)","Xcelys Medicare (Domestic)","Xcelys Medicare (Global)","Xcelys OIC Volumes"]
    """
    try:
        db_manager = core_utils.get_db_manager(RawData)
        df:pd.DataFrame = db_manager.get_raw_data_df_current('medicare_medicaid_summary',summary_type, month, year)
        if df.empty:
            logger.info(f"No data found for summary type: {summary_type} for {month} {year}")
            return pd.DataFrame()  # Return empty DataFrame if no data
        return df
    except Exception as e:
        logger.error(f"Error retrieving summary data for {summary_type}: {e}")
        return pd.DataFrame()

def get_combined_summary_excel(month: str, year: int) -> BytesIO:
    """
    Generates a combined summary Excel file for the given month and year.

    Args:
        month: Month name (e.g., "January", "February")
        year: Year as integer (e.g., 2025)

    Returns:
        BytesIO: Excel file stream with multiple summary sheets

    Raises:
        ValueError: If no summaries found or data access fails
    """
    try:
        # Get database manager
        try:
            db_manager = core_utils.get_db_manager(RawData)
        except Exception as e:
            logger.error(f"Failed to initialize database manager: {e}")
            raise ValueError(f"Database connection error: {str(e)}") from e

        # Retrieve summaries
        try:
            summaries = db_manager.get_all_current_data_models_of_raw_data("medicare_medicaid_summary", month, year)
        except Exception as e:
            logger.error(f"Database error retrieving summaries for {month} {year}: {e}", exc_info=True)
            raise ValueError(f"Failed to retrieve summaries: {str(e)}") from e

        if not summaries:
            logger.warning(f"No summaries found for month={month}, year={year}")
            raise ValueError(f"Data not found for month: {month} and year: {year}")

        logger.debug(f"Found {len(summaries)} summaries for {month} {year}")

        # Create Excel file
        output = BytesIO()
        sheets_written = 0

        try:
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                for idx, summary in enumerate(summaries):
                    try:
                        # Extract dataframe
                        df = summary.dataframe_json
                        if df is None or (hasattr(df, 'empty') and df.empty):
                            logger.warning(f"Empty dataframe for summary type: {getattr(summary, 'data_model_type', f'index {idx}')}")
                            continue

                        # Generate sheet name (max 31 characters for Excel)
                        sheet_name = str(getattr(summary, 'data_model_type', f'Sheet{idx}'))[:31]

                        # Write to Excel
                        df.to_excel(writer, sheet_name=sheet_name, index=True)
                        sheets_written += 1
                        logger.debug(f"Written sheet: {sheet_name}")

                    except Exception as e:
                        logger.error(f"Error writing summary sheet {idx} ({getattr(summary, 'data_model_type', 'unknown')}): {e}")
                        # Continue with other summaries instead of failing completely
                        continue

                if sheets_written == 0:
                    raise ValueError(f"No valid summary data could be written for {month} {year}")

        except ValueError:
            # Re-raise ValueError (already has descriptive message)
            raise
        except Exception as e:
            logger.error(f"Error creating Excel writer or writing sheets: {e}", exc_info=True)
            raise ValueError(f"Failed to create Excel file: {str(e)}") from e

        output.seek(0)
        logger.info(f"Successfully created combined summary Excel with {sheets_written} sheets for {month} {year}")
        return output

    except ValueError:
        # Re-raise ValueError as-is
        raise
    except Exception as e:
        logger.error(f"Unexpected error generating combined summary Excel for {month} {year}: {e}", exc_info=True)
        raise ValueError(f"Unexpected error creating summary file: {str(e)}") from e


def create_combined_summary_excel(folder_path: str) -> BytesIO:
    output = BytesIO()
    sheets_written = 0

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for filename in os.listdir(folder_path):
            if filename.endswith(".xlsx"):
                file_path = os.path.join(folder_path, filename)
                try:
                    
                    df = construct_grouped_summary_df(file_path)
                    
                    # Generate a clean sheet name
                    sheet_name = filename.replace("-summary.xlsx", "").strip()[:31]
                    if df.empty:
                        logger.warning(f"No data in file {filename}, writing empty sheet.")
                        pd.DataFrame().to_excel(writer, sheet_name=sheet_name, index=True)
                    else:
                        df.to_excel(writer, sheet_name=sheet_name, index=True)
                    # df.to_excel(writer, sheet_name=sheet_name, index=True)
                    sheets_written += 1

                except Exception as e:
                    logger.error(f"Error processing {filename}: {e}")

        if sheets_written == 0:
            pd.DataFrame({"Error": ["No valid Excel files processed"]}).to_excel(
                writer, sheet_name="Error", index=False
            )

    output.seek(0)
    return output


def upload_calculations_data():
    file_path = os.path.join(BASE_DIR, "logics", "data", "constants", "calculations.xlsx")
    sheets = pd.read_excel(file_path, sheet_name=["Sheet1", "Target_cph"])
    items = []
    month: str = 'July'
    year: int = 2025
    df_month_data = sheets["Sheet1"]
    df_month_data.iloc[:,1:]= df_month_data.iloc[:,1:].fillna(0)
    # Convert selected columns to int
    int_cols = ["No.of days occupancy", "Work hours"]
    df_month_data[int_cols] = df_month_data[int_cols].astype(int)

    # Convert selected columns to float
    float_cols = ["Occupancy", "Shrinkage"]
    df_month_data[float_cols] = df_month_data[float_cols].astype(float)
    raw_data = {
        'df': df_month_data,
        'data_model': 'calculations',
        'data_model_type': 'month_data',
        'month': month,
        'year': year,
        'created_by': 'Aswanth Ravikumar Jaya'
    }
    items.append(raw_data)

    df_target_cph = sheets["Target_cph"]
    raw_data = {
        'df': df_target_cph,
        'data_model': 'calculations',
        'data_model_type': 'target_cph',
        'month': month,
        'year': year,
        'created_by': 'Aswanth Ravikumar Jaya'
    }
    items.append(raw_data)

    try:
        db_manager = core_utils.get_db_manager(RawData)
        db_manager.bulk_save_raw_data_with_history(items)
    except Exception as e:
        logger.error(f"Error updating raw data: {e}")






def update_forecast_data(df:pd.DataFrame, month: str, year:int, uploaded_by: str = "System", filename: str ="Forecast File"):
    """
    Dataframe of updated forecast model will be updated in database
    Args:
    Forecast dataframe, month in Capitalised full name (e.g, January, February, ...), year(YYYY) in integer
    """
    try:
        file_id = "forecast"
        meta_info = {
            "Month": month,
            "Year": year,
            "CreatedBy": uploaded_by,
            "UpdatedBy": uploaded_by,
            "UploadedFile": filename
        }
        Model = get_model_or_all_models(file_id)
        db_manager = core_utils.get_db_manager(Model)
        for col, val in meta_info.items():
            df[col] = val
        db_manager = core_utils.get_db_manager(Model)
        db_manager.save_to_db(df, replace=True)
        logger.info(f"Successfully updated forecast summary for {month} {year}.")
    except Exception as e:
        logger.error(f"Error updating forecast summary for {month} {year}: {e}")


def test_result_file_update():
    month = "July"
    year = 2025
    result_file = os.path.join(BASE_DIR, 'logics', 'result.xlsx')
    preprocessor = PreProcessing("forecast")

    df = preprocessor.preprocess_file(result_file)
    update_forecast_data(df,month, year, 'Ash')

def get_all_model_types(model:str, month:str=None, year:int=None):
    """
    A funtion to return model types (different summaries, non mmp/ mmp types)
    model: ["medicare_medicaid_summary", "medicare_medicaid_nonmmp", "medicare_medicaid_mmp", "calculations", "worktypes", "combinations"]
    """
    try:
        db_manager = core_utils.get_db_manager(RawData)
        model_types = db_manager.get_all_current_data_models_of_raw_data(model,month, year)
        if not (model_types and len(model_types)>0):
            logger.info(f" No data found for data_model: {model} month: {month} year: {year}")
        else:
            for model_type in model_types:
                logger.info(f"Got data for data model: {model} model type: {model_type.data_model_type}, Month: {model_type.month}, Year: {model_type.year}")
        return model_types
    except Exception as e:
        logger.error(f"Error retrieving data model: {model} for month: {month} year: {year} is : {e}")
        return []
    
def get_all_summaries(month: str = None, year: int = None):
    """
    Retrieve all medicare_medicaid_summary records from the database.
    """
    return get_all_model_types('medicare_medicaid_summary', month, year)

def get_all_nonmmps(month: str = None, year: int = None):
    """
    Retrieve all medicare_medicaid_nonmmp records from the database.
    """
    return get_all_model_types('medicare_medicaid_nonmmp', month, year)

def get_all_mmps(month: str = None, year: int = None):
    """
    Retrieve all medicare_medicaid_mmp records from the database.
    """
    return get_all_model_types('medicare_medicaid_mmp', month, year)

def get_all_calculations(month: str = None, year: int = None):
    """
    Retrieve all calculations records from the database.
    """
    return get_all_model_types('calculations', month, year)

def get_all_worktypes(month: str = None, year: int = None):
    """
    Retrieve all worktypes records from the database.
    """
    return get_all_model_types('worktypes', month, year)

def get_all_combinations(month: str = None, year: int = None):
    """
    Retrieve all combinations records from the database.
    """
    return get_all_model_types('combinations', month, year)
    

def get_all_model_dataframes_dict(month: str, year: int) -> dict[str, dict[str, pd.DataFrame]]:
    """
    Returns a nested dictionary of dataframes for the three main models:
    ["medicare_medicaid_summary", "medicare_medicaid_nonmmp", "medicare_medicaid_mmp"]
    Structure: {model: {model_type: dataframe}}
    Tries with month/year first, falls back to all data if empty.
    """
    models = [
        "medicare_medicaid_mmp",
        "medicare_medicaid_nonmmp",
        "medicare_medicaid_summary",
    ]
    result = {}

    for model in models:
        try:
            model_types = get_all_model_types(model, month, year)
            if not model_types:
                logger.warning(f"No data found for {model} with month={month}, year={year}. Trying without month/year.")
                model_types = get_all_model_types(model)
            if not model_types:
                logger.error(f"No data found for {model} even without month/year.")
                result[model] = {}
                continue

            result[model] = {}
            for mt in model_types:
                try:
                    # dataframe_json is assumed to be a DataFrame
                    if model == 'medicare_medicaid_summary' and mt.data_model_type in ['AMISYS MMP Domestic', 'AMISYS MMP Global' ,'Amisys Medicaid DOMESTIC', 'Amisys Medicaid GLOBAL']:
                        continue
                    result[model][mt.data_model_type] = mt.dataframe_json
                except Exception as e:
                    logger.error(f"Error extracting dataframe for {model} type {getattr(mt, 'data_model_type', None)}: {e}")
        except Exception as e:
            logger.error(f"Error fetching model types for {model}: {e}")
            result[model] = {}

    return result

def test_save_summary_stream_to_file(file_path: str = None, output_filename: str = "summary.xlsx"):
    """
    Calls get_summary_excel() or get_combined_summary_excel() to generate a BytesIO stream from the given Excel file
    and writes it to summary.xlsx (or custom filename).
    """
    if file_path:
        # If a specific file path is provided, use that to generate the summary
        stream = create_combined_summary_excel(file_path)
    else:
        stream = get_combined_summary_excel("July", 2025)
    with open(output_filename, "wb") as f:
        f.write(stream.getbuffer())
    print(f"Saved summary file to: {output_filename}")


def process_and_upload_excel_files(
    folder_path: str,
    data_model: str,
    sheet_name_cleaner: callable,
    df_constructor: callable,
    month: str = 'August',
    year: int = 2025,
    created_by: str = 'Aswanth Ravikumar Jaya'
):
    """
    Generic function to process Excel files in a folder and upload summaries to the database.
    Args:
        folder_path: Path to the folder containing Excel files.
        data_model: String identifier for the data model.
        sheet_name_cleaner: Function to clean the sheet/file name.
        df_constructor: Function to construct the DataFrame from file.
        month, year, created_by: Metadata for the summary.
    """
    try:
        db_manager = core_utils.get_db_manager(RawData)
        items = []
        for filename in os.listdir(folder_path):
            if filename.endswith(".xlsx"):
                file_path = os.path.join(folder_path, filename)
                try:
                    df = df_constructor(file_path)
                    sheet_name = sheet_name_cleaner(filename)
                    raw_data = {
                        'df': df,
                        'data_model': data_model,
                        'data_model_type': sheet_name,
                        'month': month,
                        'year': year,
                        'created_by': created_by
                    }
                    items.append(raw_data)
                    logger.info(f"Processed {filename} successfully.")
                except Exception as e:
                    logger.error(f"Error processing {filename}: {e}")
                    continue
        db_manager.bulk_save_raw_data_with_history(items)
    except Exception as e:
        logger.error(f"Error updating raw data: {e}")

# Usage replacements for previous functions:
def test_update_summaries():
    process_and_upload_excel_files(
        folder_path=os.path.join(BASE_DIR, "logics", "data", "constants", "medicare_medicaid_summary"),
        data_model='medicare_medicaid_summary',
        sheet_name_cleaner=lambda fn: fn.replace("-summary.xlsx", "").strip(),
        df_constructor=construct_grouped_summary_df
    )

def test_upload_mmps():
    process_and_upload_excel_files(
        folder_path=os.path.join(BASE_DIR, "logics", "data", "constants", "medicare_medicaid_mmp"),
        data_model='medicare_medicaid_mmp',
        sheet_name_cleaner=lambda fn: fn.replace(".xlsx", "").strip(),
        df_constructor=construct_mmp_df
    )

def test_upload_non_mmps():
    process_and_upload_excel_files(
        folder_path=os.path.join(BASE_DIR, "logics", "data", "constants", "medicare_medicaid_nonmmp"),
        data_model='medicare_medicaid_nonmmp',
        sheet_name_cleaner=lambda fn: fn.replace(".xlsx", "").strip(),
        df_constructor=construct_nonmmp_df
    )

def upload_combinations_data():
    file_path = os.path.join(BASE_DIR, "logics", "data", "constants", "combinations_2.xlsx")
    combination_df = pd.read_excel(file_path, sheet_name="Sheet1")
    combination_df = combination_df.fillna("").astype(str)  
    items = []
    month: str = 'August'
    year: int = 2025
    raw_data = {
        'df': combination_df,
        'data_model': 'combinations',
        'data_model_type': 'combination',
        'month': month,
        'year': year,
        'created_by': 'Aswanth Ravikumar Jaya'
    }
    items.append(raw_data)
    try:
        db_manager = core_utils.get_db_manager(RawData)
        db_manager.bulk_save_raw_data_with_history(items)
    except Exception as e:
        logger.error(f"Error updating raw data: {e}")


def upload_worktypes():
    file_path = os.path.join(BASE_DIR, "logics", "data", "constants", "worktypes.xlsx")
    df = pd.read_excel(file_path, sheet_name=0)

    df.columns = df.columns.str.strip()

    dfs_by_col = {col: df[[col]].dropna().reset_index(drop=True).copy() for col in df.columns}
    items = []
    month: str = 'August'
    year: int = 2025
    for worktype, value in dfs_by_col.items():
        raw_data = {
            'df': value,
            'data_model': 'worktypes',
            'data_model_type': worktype,
            'month': month,
            'year': year,
            'created_by': 'Aswanth Ravikumar Jaya'
        }
        items.append(raw_data)
    try:
        db_manager = core_utils.get_db_manager(RawData)
        db_manager.bulk_save_raw_data_with_history(items)
    except Exception as e:
        logger.error(f"Error updating raw data: {e}")

def get_calculations_data(month: str=None, year: int= None) -> dict[str, pd.DataFrame]:
    result = {}
    model = 'calculations'
    try:
        model_types = get_all_model_types(model, month, year)
        if not model_types:
            logger.warning(f"No data found for {model} with month={month}, year={year}. Trying without month/year.")
            model_types = get_all_model_types(model)
        if not model_types:
            logger.error(f"No data found for {model} even without month/year.")
        else:
            for mt in model_types:
                try:
                    # dataframe_json is assumed to be a DataFrame
                    result[mt.data_model_type] = mt.dataframe_json
                except Exception as e:
                    logger.error(f"Error extracting dataframe for {model} type {getattr(mt, 'data_model_type', None)}: {e}")

    except Exception as e:
        logger.error(f"Error fetching model types for {model}: {e}")
        result[model] = {}
    
    return result

def get_month_and_year_dropdown() -> Dict[str, List[int|str]]:
    """
    Returns available months and years for dropdowns.
    Structure: {"months": [...], "years": [...]}
    """
    try:
        db_manager = core_utils.get_db_manager(UploadDataTimeDetails, limit=1)
        res = db_manager.read_db()
        db_manager = core_utils.get_db_manager(UploadDataTimeDetails, limit=res.get("total", 0),select_columns=["Year"])
        years_res = db_manager.read_db()
        years = sorted([year_dict.get("Year",) for year_dict in years_res["records"]], reverse=True)
        db_manager = core_utils.get_db_manager(UploadDataTimeDetails, limit=res.get("total", 0), select_columns=["Month"])
        months_res = db_manager.read_db()

        # Create a mapping of month name -> month number
        month_order = {month: index for index, month in enumerate(calendar.month_name) if month}

        months = sorted(
            list(set([month_dict.get("Month",) for month_dict in months_res["records"]])),
            key=lambda m: month_order.get(m, 13)  
        )
        return {"months": months, "years": years}
    except Exception as e:
        logger.error(f"Error fetching month and year dropdowns: {e}")
        return {"months": [], "years": []}

# --- Find column indices where the 2nd header row is a month name ---
def month_columns_by_level(
    df: pd.DataFrame,
    level: int = 1,                 # "second row" of header = level 1 (0-based)
    months: list[str] | None = None,
    match_abbrev: bool = True,      # also match Jan, Feb, ... if True
    case_insensitive: bool = True
) -> list[int]:
    """
    For a DataFrame with MultiIndex columns, return integer positions of columns
    where the value at `level` is a month name.

    - level: which level to inspect (0-based). 1 means "second row".
    - months: override recognized months (default English month names).
    - match_abbrev: also match 3-letter abbreviations if True.
    - case_insensitive: case-insensitive matching if True.
    """
    if not isinstance(df.columns, pd.MultiIndex):
        raise TypeError("DataFrame must have MultiIndex columns")

    if months is None:
        months = [
            "January","February","March","April","May","June",
            "July","August","September","October","November","December"
        ]
    # Build patterns
    allowed = set(m.strip() for m in months)
    abbrev = {m[:3] for m in allowed} if match_abbrev else set()

    flags = re.IGNORECASE if case_insensitive else 0

    patterns = [re.compile(rf"^{re.escape(m)}$", flags) for m in allowed]
    patterns_abbrev = [re.compile(rf"^{re.escape(a)}$", flags) for a in abbrev]

    idxs = []
    # Iterate over columns with their integer positions
    for i, tup in enumerate(df.columns):
        # tup is a tuple of level values
        if level >= len(tup):
            continue
        val = str(tup[level]).strip()
        if any(p.fullmatch(val) for p in patterns) or any(p.fullmatch(val) for p in patterns_abbrev):
            idxs.append(i)
    return idxs


# --- Helper: normalize and validate integer indices -> column names ---
def _cols_from_indices(df: pd.DataFrame, col_indices):
    """
    Map a list/iterable of integer indices (supports negatives) to column names.
    Raises IndexError on out-of-range. Preserves order and uniqueness.
    """
    if col_indices is None:
        # Default: all numeric columns by dtype
        return df.select_dtypes(include=[np.number]).columns.tolist()

    n = len(df.columns)
    names = []
    for idx in col_indices:
        if not isinstance(idx, int):
            raise TypeError(f"Column index must be int, got {type(idx)}")
        # Python-style negative indexing support
        real_idx = idx if idx >= 0 else n + idx
        if real_idx < 0 or real_idx >= n:
            raise IndexError(f"Column index {idx} out of range for {n} columns")
        names.append(df.columns[real_idx])
    return names

# --- Total row using column indices instead of names ---
def add_totals_row_by_index(
    df: pd.DataFrame,
    sum_col_idx=None,               # e.g., [2, 3] or [-2, -1]; None -> auto-detect numeric
    label_col_idx=None,             # e.g., 0 to place "Total" in first column
    label_value="Total"
):
    """
    Append a totals row computed over columns designated by integer indices.
    Returns (df_with_total, total_row_idx).
    """
    out = df.copy()
    sum_cols = _cols_from_indices(out, sum_col_idx)

    # Compute totals for selected columns
    totals_map = {col: out[col].sum(min_count=1) for col in sum_cols}

    # Build a full totals row aligned to out.columns
    totals_full = pd.Series(index=out.columns, dtype=object)

    # Fill totals for selected columns; empty strings elsewhere
    for col in out.columns:
        if col in sum_cols:
            totals_full[col] = totals_map[col]
        else:
            totals_full[col] = ""

    # Put the label in the chosen label column (if provided)
    if label_col_idx is not None:
        label_col = _cols_from_indices(out, [label_col_idx])[0]
        totals_full[label_col] = label_value

    out = pd.concat([out, totals_full.to_frame().T], ignore_index=True)
    return out, out.index[-1]

def export_with_total_formatting(df_with_total: pd.DataFrame, total_row_idx: int, header_offset:int = 1, sheet_name="Sheet1") -> BytesIO:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_with_total.to_excel(writer, index=True, sheet_name=sheet_name)

        wb = writer.book
        ws = writer.sheets[sheet_name]

        bold_fmt = wb.add_format({"bold": True})
        num_fmt  = wb.add_format({"num_format": "#,##0"})

        # Bold header
        ws.set_row(0, None, bold_fmt)
        # Bold the totals row (header is row 0 in Excel)
        excel_total_row = total_row_idx + header_offset
        ws.set_row(excel_total_row, None, bold_fmt)

        # Best-effort: apply numeric format to numeric-looking columns
        header = list(df_with_total.columns)
        for c_idx, col in enumerate(header):
            # For MultiIndex, try to detect numeric dtype via the first data row
            series = df_with_total[col] if isinstance(col, tuple) else df_with_total[str(col)] \
                     if str(col) in df_with_total.columns else df_with_total[col]
            if pd.api.types.is_numeric_dtype(series):
                ws.set_column(c_idx, c_idx, 12, num_fmt)
    output.seek(0)
    return output


def download_forecast_excel(month, year) -> BytesIO:
    """
    Download forecast data as formatted Excel file with totals row.

    Args:
        month: Month name (e.g., "January", "February")
        year: Year as integer (e.g., 2025)

    Returns:
        BytesIO: Excel file stream

    Raises:
        ValueError: If data not found or processing fails
        TypeError: If DataFrame doesn't have MultiIndex columns
    """
    file_id = "forecast"

    try:
        # Get processed dataframe
        df = get_processed_dataframe(file_id, month, year)
    except ValueError as ve:
        logger.error(f"Failed to get processed dataframe: {ve}")
        raise ValueError(f"Cannot download forecast: {str(ve)}") from ve
    except Exception as e:
        logger.error(f"Unexpected error getting forecast data for {month} {year}: {e}", exc_info=True)
        raise ValueError(f"Unexpected error retrieving forecast data: {str(e)}") from e

    if df.empty:
        logger.error(f"No data found for {file_id} - {month} {year}")
        raise ValueError(f"Data not found for the month {month} - year {year}")

    logger.info(f"Fetched Data for {file_id} - month: {month} year: {year}")

    try:
        # Find month columns for totals calculation
        indexes = month_columns_by_level(df)
        if not indexes:
            logger.warning(f"No month columns found in forecast data for {month} {year}")
    except TypeError as te:
        logger.error(f"DataFrame structure error: {te}")
        raise ValueError(f"Invalid forecast data structure: DataFrame must have MultiIndex columns") from te
    except Exception as e:
        logger.error(f"Error identifying month columns: {e}", exc_info=True)
        raise ValueError(f"Failed to identify month columns in forecast data: {str(e)}") from e

    try:
        # Add totals row
        mod_df, total_row = add_totals_row_by_index(df, indexes, label_col_idx=0)
    except (IndexError, TypeError) as e:
        logger.error(f"Error adding totals row: {e}")
        raise ValueError(f"Failed to add totals row to forecast data: {str(e)}") from e
    except Exception as e:
        logger.error(f"Unexpected error adding totals row: {e}", exc_info=True)
        raise ValueError(f"Unexpected error processing forecast data: {str(e)}") from e

    try:
        # Export to Excel with formatting
        output = export_with_total_formatting(mod_df, total_row, header_offset=3)
        logger.info(f"Successfully created Excel file for {month} {year}")
        return output
    except Exception as e:
        logger.error(f"Error exporting to Excel: {e}", exc_info=True)
        raise ValueError(f"Failed to create Excel file: {str(e)}") from e

def drop_keys_many(dicts: Iterable[Mapping], keys_to_remove: Iterable) -> List[Dict]:
    """
    Returns new dicts with keys removed; originals unchanged.
    O(len(dict)) per dict due to full copy, but very fast in CPython.
    """
    ks = set(keys_to_remove)
    contains = ks.__contains__        # micro-opt: local binding
    return [{k: v for k, v in d.items() if not contains(k)} for d in dicts]

def update_summary_data(month:str, year:int):
    file_id = "forecast"
    forecast_df = get_processed_dataframe(file_id, month, year)
    if forecast_df is None or forecast_df.empty:
        logger.error(f"forecast file not found for month: {month} year: {year}")
        return
    model = 'medicare_medicaid_summary'
    summary_model_types = get_all_model_types(model, month, year)
    if summary_model_types is None or isinstance(summary_model_types, List) and len(summary_model_types)<=0:
        logger.error(f"summary data not available for month: {month} year: {year}")
        return
    # summary_data = {m.data_model_type: m.dataframe_json for m in summary_model_types[:1]}
    keys_to_delete = ['created_on', 'created_by', 'updated_on', 'updated_by', 'is_current', 'id', 'version']
    summary_model_types = [dict(summary_type) for summary_type in summary_model_types]
    summary_model_types = drop_keys_many(summary_model_types, keys_to_delete)   
    summaries = []
    for summary_type_dict in summary_model_types[:1]:
        summaries.append(summary_type_dict)
        print(summary_type_dict)

    test_export_summaries_to_excel(summaries)
    pass

def test_export_summaries_to_excel(summaries):
    output_base = BASE_DIR
    
    folder_path = os.path.join(output_base, "forecast_summaries")
    os.makedirs(folder_path, exist_ok=True)
    for summary_dict in summaries:
        file_path = os.path.join(folder_path, f"{summary_dict.get('data_model_type','output')}.xlsx")
        summary_dict.get('dataframe_json',pd.DataFrame()).to_excel(file_path)

def test_update_summary_data():
    month= "March"
    year = 2025
    update_summary_data(month, year)

def test_forecast_month_lists(filename:str=None):
    months = get_forecast_months_list('February', 2025, filename)
    print(months)

def test_get_all_model_dataframes_dict():
    month = "July"
    year = 2025
    result = get_all_model_dataframes_dict(month, year)
    for model, types_dict in result.items():
        print(f"Model: {model}")
        for model_type, df in types_dict.items():
            print(f"  Model Type: {model_type}, DataFrame shape: {df.shape if hasattr(df, 'shape') else 'N/A'}")

def test_get_calculations_data():
    result = get_calculations_data()
    for model_type, df in result.items():
        print(f"  Model Type: {model_type}, DataFrame shape: {df.shape if hasattr(df, 'shape') else 'N/A'}")
        print(f"df columns - {df.columns.to_list()}")

def test_upload_data_time_details():
    try:
        db_manager = core_utils.get_db_manager(UploadDataTimeDetails)
        time_data = [
            {"Month": "July", "Year": 2025},
            {"Month": "August", "Year": 2025},
            {"Month": "July", "Year": 2025},
            {"Month": "February", "Year": 2025},
            {"Month": "August", "Year": 2024},
            {"Month": "July", "Year": 2024},
        ]
        for data in time_data:
            db_manager.insert_upload_data_time_details_if_not_exists(data["Month"], data["Year"])
        print("Upload time details updated successfully.")
        dropdown_options = get_month_and_year_dropdown()
        print(f"Dropdown options: {dropdown_options}")
    except Exception as e:
        print(f"Error updating upload time details: {e}")

def test_download_forecast_dataframe():
    output = download_forecast_excel('February', 2025)
    with open("forecast_output.xlsx", "wb") as f:
        f.write(output.getbuffer())
    print("Saved forecast_output.xlsx")



if __name__ == "__main__":
    # Example usage
    file_id = "skilling"
    month = "March"
    year = 2025
    folder_path = os.path.join(BASE_DIR, "logics", "data", "constants", "medicare_medicaid_mmp")
    file_path = os.path.join(folder_path,"AMISYS MMP Domestic.xlsx")
    # save_summary_stream_to_file(folder_path)
    # test_result_file_update()
    # test_forecast_month_lists()
    # test_update_summaries()
    # test_save_summary_stream_to_file()
    # df=construct_mmp_df(file_path)
    # print(df.columns)
    # print(df.shape)
    # test_upload_mmps()
    # test_upload_non_mmps()
    # test_update_summaries()
    upload_calculations_data()
    # upload_combinations_data()
    # upload_worktypes()
    # test_get_all_model_dataframes_dict()
    # test_get_calculations_data()
    # test_upload_data_time_details()
    # test_download_forecast_dataframe()
    # test_update_summary_data()
    
    
    
    
    pass
    # df = get_latest_or_requested_dataframe(file_id, month, year)
    # print(df.head())


