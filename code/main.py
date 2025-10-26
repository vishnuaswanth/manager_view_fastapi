from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from typing import List, Optional, Dict
from copy import deepcopy
from datetime import datetime, timezone


import pandas as pd
import io
import logging
import os
from code.settings import  (
    MODE,
    SQLITE_DATABASE_URL,
    MSSQL_DATABASE_URL,
    setup_logging,
    BASE_DIR
)

from code.logics.db import (
    InValidSearchException,
    ForecastMonthsModel,
    ForecastModel,
    RawData,
    UploadDataTimeDetails
)
# from logics.allocation import process_files
from fastapi.responses import StreamingResponse, HTMLResponse

from fastapi import BackgroundTasks
from code.logics.allocation import process_files
from code.logics.core_utils import (
    get_model_or_all_models,
    CoreUtils,
    PreProcessing,
    PostProcessing,
    insert_file_id,
    to_title_case
)
from code.logics.export_utils import (
    get_combined_summary_excel,
    get_summary_data_by_summary_type,
    get_month_and_year_dropdown,
    download_forecast_excel,
)
from code.logics.manager_view import (
    get_available_report_months,
    get_category_list,
    build_category_tree,
    get_forecast_months_from_db,
    load_category_config,
    diagnose_record_categorization,
)
from code.logics.cache_utils import TTLCache
import re

setup_logging()

# Validate forecast grouping config at startup
try:
    logger.info("[Startup] Validating forecast grouping configuration...")
    load_category_config()  # This will validate and raise exception if invalid
    logger.info("[Startup] Forecast grouping configuration validated successfully")
except (FileNotFoundError, ValueError) as e:
    logger.critical(f"[Startup] FATAL: Invalid forecast grouping configuration: {e}")
    logger.critical("[Startup] Application cannot start with invalid configuration")
    raise RuntimeError(f"Application startup failed: {e}") from e

if MODE.upper() == "DEBUG":
    DATABASE_URL = SQLITE_DATABASE_URL
elif MODE.upper() == "PRODUCTION":
    DATABASE_URL = MSSQL_DATABASE_URL
else:
    raise ValueError("Invalid MODE specified in config.")

# Step 2: Initialize the CoreUtils instance with final DB URL
core_utils = CoreUtils(DATABASE_URL)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Centene Forecasting Endpoints",
    description="Endpoints covered: File upload, File upload history, Forecast table schema, month filter, filtered query, roster table, Global search",
    version="0.1.1", # release.patch.internal version
)

# Initialize caches per API spec
# Filters: 5 minutes TTL, max 8 entries
# Data: 60 seconds TTL, max 64 entries
filters_cache = TTLCache(max_size=8, ttl_seconds=300)
data_cache = TTLCache(max_size=64, ttl_seconds=60)


# ==================== CASCADE FILTER HELPER FUNCTIONS ====================

# Known platforms and localities (case-insensitive matching)
CASCADE_PLATFORMS = ["amisys", "facets", "xcelys"]
CASCADE_LOCALITIES = ["domestic", "global", "(domestic)", "(global)"]


def parse_main_lob_preserve_case(main_lob: str) -> Dict[str, Optional[str]]:
    """
    Parse main_lob into platform, market, and locality components while PRESERVING original case.

    This is similar to manager_view.parse_main_lob but keeps original case for filter values.

    Format: <platform> <market> [<locality>]
    - Platform: Amisys, Facets, or Xcelys (first word if it matches known platforms)
    - Locality: Domestic or Global (last word if it matches known localities)
    - Market: Everything in between

    Args:
        main_lob: String like "Amisys Medicaid Domestic" or "Facets OIC Volumes"

    Returns:
        Dict with keys: platform, market, locality (preserving original case)
    """
    if not main_lob or not isinstance(main_lob, str):
        return {"platform": None, "market": None, "locality": None}

    main_lob_cleaned = main_lob.strip()
    if not main_lob_cleaned:
        return {"platform": None, "market": None, "locality": None}

    parts = main_lob_cleaned.split()

    if len(parts) == 1:
        single_token = parts[0]
        if single_token.lower() in CASCADE_PLATFORMS:
            return {"platform": single_token, "market": None, "locality": None}
        elif single_token.lower() in CASCADE_LOCALITIES:
            return {"platform": None, "market": None, "locality": single_token}
        else:
            return {"platform": None, "market": single_token, "locality": None}

    platform = None
    locality = None
    market_parts = []

    # Check first part for platform (case-insensitive match, preserve original)
    if parts[0].lower() in CASCADE_PLATFORMS:
        platform = parts[0]  # Preserve original case
        remaining_parts = parts[1:]
    else:
        remaining_parts = parts

    # Check last part for locality (case-insensitive match, preserve original)
    if remaining_parts and remaining_parts[-1].lower() in CASCADE_LOCALITIES:
        locality = remaining_parts[-1]  # Preserve original case
        market_parts = remaining_parts[:-1]
    else:
        market_parts = remaining_parts

    # Everything else is market (preserve original case)
    market = " ".join(market_parts) if market_parts else None

    return {
        "platform": platform,
        "market": market,
        "locality": locality
    }


def extract_unique_cascade_values(
    records: List[Dict],
    component: str,
    platform_filter: Optional[str] = None,
    market_filter: Optional[str] = None,
    locality_filter: Optional[str] = None
) -> List[str]:
    """
    Extract unique values for a specific LOB component from forecast records.

    Args:
        records: List of forecast records with Centene_Capacity_Plan_Main_LOB field
        component: Which component to extract ('platform', 'market', or 'locality')
        platform_filter: Filter by platform before extracting (case-insensitive)
        market_filter: Filter by market before extracting (case-insensitive)
        locality_filter: Filter by locality before extracting (case-insensitive)

    Returns:
        List of unique values for the component (sorted, case preserved)
    """
    unique_values = set()

    for record in records:
        main_lob = record.get("Centene_Capacity_Plan_Main_LOB", "")
        if not main_lob:
            continue

        parsed = parse_main_lob_preserve_case(main_lob)

        # Apply filters (case-insensitive comparison)
        if platform_filter and (not parsed.get("platform") or parsed["platform"].lower() != platform_filter.lower()):
            continue
        if market_filter and (not parsed.get("market") or parsed["market"].lower() != market_filter.lower()):
            continue
        if locality_filter and (not parsed.get("locality") or parsed["locality"].lower() != locality_filter.lower()):
            continue

        # Extract the requested component
        value = parsed.get(component)
        if value:
            unique_values.add(value)

    return sorted(list(unique_values))


def generate_cascade_cache_key(prefix: str, **params) -> str:
    """
    Generate a cache key for cascade endpoints with sorted parameters.

    Args:
        prefix: Cache key prefix (e.g., 'cascade:platforms')
        **params: Query parameters to include in cache key

    Returns:
        Cache key string with sorted params
    """
    sorted_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
    if sorted_params:
        return f"{prefix}:{sorted_params}"
    return f"{prefix}:ALL"


def invalidate_forecast_cache(month: str, year: int):
    """
    Invalidate all cached data for a specific forecast month.

    This clears:
    - Manager view filters cache (report months, categories)
    - Cascade filter caches (years, months, platforms, markets, localities, worktypes)
    - Data caches for the specific month

    Args:
        month: Month name (e.g., "February")
        year: Year as integer
    """
    from calendar import month_name as cal_month_name

    try:
        # Convert month name to YYYY-MM format
        month_num = list(cal_month_name).index(month.strip().capitalize())
        report_month_key = f"{year}-{month_num:02d}"

        # Clear filters cache (includes manager view filters and ALL cascade filters)
        filters_cache.clear()
        logger.info(f"[Cache] Cleared filters cache (manager view + cascade) due to forecast upload: {month} {year}")

        # Clear all data cache entries for this month (all categories)
        # Pattern: "data:v1:YYYY-MM:" will match all categories for this month
        deleted_count = data_cache.delete_pattern(f"data:v1:{report_month_key}:")
        logger.info(f"[Cache] Cleared {deleted_count} data cache entries for {month} {year}")

    except Exception as e:
        logger.error(f"[Cache] Error invalidating cache for {month} {year}: {e}")


@app.get("/")
def default():
    return {"Success":"Centene forecasting default"}

@app.post("/upload/{file_id}")
async def upload_file(
    file_id:str, user:str,
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None
    ):


    Model = get_model_or_all_models(file_id)

    if not Model:
        raise HTTPException(status_code=400, detail="Unknown file_id")

    if not file.filename.endswith(('.xlsx', '.xlsm', '.csv')):
        raise HTTPException(status_code=400, detail="Invalid file type.")

    contents = await file.read()
    pre_processor = PreProcessing(file_id)
    month_year = pre_processor.get_month_year(file.filename)
    if not month_year:
        raise HTTPException(status_code=400, detail="Filename must contain month and year (e.g., Jan_2024 or January-2024).")

    meta_info = {
        "Month": month_year["Month"],
        "Year": int(month_year["Year"]),
        "CreatedBy": user,
        "UpdatedBy": user,
        "UploadedFile": file.filename
    }

    if file_id == "upload_roster":
        try:
            excel_io = io.BytesIO(contents)
            sheets = pd.read_excel(excel_io, sheet_name=["Roster", "Skilling"])

            # -- Process Roster sheet --
            roster_df = pre_processor.preprocess_roster(sheets["Roster"])
            for col, val in meta_info.items():
                roster_df[col] = val
            db_manager_roster = core_utils.get_db_manager(Model["Roster"])
            db_manager_roster.save_to_db(roster_df, replace=True)

            # -- Process Skilling sheet --
            skilling_df = pre_processor.preprocess_skilling(sheets["Skilling"])
            for col, val in meta_info.items():
                skilling_df[col] = val
            db_manager_skilling = core_utils.get_db_manager(Model["Skilling"])
            db_manager_skilling.save_to_db(skilling_df, replace=True)

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error processing roster file: {str(e)}")

    elif file_id == "forecast":
        try:
            dfs = pre_processor.process_forecast_file(io.BytesIO(contents))
        except ValueError as ve:
            logger.error(f"Error processing forecast file: {ve}")
            raise HTTPException(status_code=400, detail=str(ve))
        except Exception as e:
            logger.error(f"Unexpected error processing forecast file: {e}")
            raise HTTPException(status_code=500, detail="Error processing forecast file.")
        try:
            items = []
            for data_model, model_type_dict in dfs.items():
                for data_model_type, df in model_type_dict.items():
                    raw_data = {
                        'df': df,
                        'data_model': data_model,
                        'data_model_type': data_model_type,
                        'month': meta_info.get("Month", ""),
                        'year': meta_info.get("Year", ""),
                        'created_by': user
                    }
                    items.append(raw_data)
                    logger.info(f"Processed Data Model: {data_model} | Data Model Type: {data_model_type} successfully.")
            db_manager = core_utils.get_db_manager(RawData)
            db_manager.bulk_save_raw_data_with_history(items)
        except Exception as e:
            logger.error(f"Error updating raw data: {e}")
            raise HTTPException(status_code=500, detail=f"Error processing forecast file: Upload error")
        try:
            db_manager_forecast = core_utils.get_db_manager(ForecastMonthsModel)
            forecast_meta = pre_processor.month_codes
            forecast_meta["UploadedFile"] = file.filename
            forecast_meta["CreatedBy"] = user
            forecast_df = pd.DataFrame([forecast_meta])
            db_manager_forecast.save_to_db(forecast_df)

        except Exception as e:
            logger.error(f"Error updating months: {e}")

        background_tasks.add_task(
            process_files,
            data_month=month_year["Month"],
            data_year=int(month_year["Year"]),
            forecast_file_uploaded_by=user,
            forecast_filename=file.filename
        )

        # Invalidate cache for this month after successful upload
        invalidate_forecast_cache(month_year["Month"], int(month_year["Year"]))

    else:
        df = pre_processor.preprocess_file(io.BytesIO(contents))
        if file_id == "prod_team_roster":
             for col in df.columns:
                if col.startswith("ProductionPercentage"):
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0).astype(float)
                else:
                    df[col] = df[col].fillna("").astype(str).str.strip()
        for col, val in meta_info.items():
            df[col] = val
        db_manager = core_utils.get_db_manager(Model)
        df = df.where(pd.notnull(df), None)
        db_manager.save_to_db(df, replace=True)

        # if file_id == "forecast":
        #     db_manager_forecast = core_utils.get_db_manager(ForecastMonthsModel)
        #     forecast_meta = pre_processor.month_codes
        #     forecast_meta["UploadedFile"] = file.filename
        #     forecast_meta["CreatedBy"] = user
        #     forecast_df = pd.DataFrame([forecast_meta])
        #     db_manager_forecast.save_to_db(forecast_df)

        #     background_tasks.add_task(
        #         process_files,
        #         data_month=month_year["Month"],
        #         data_year=month_year["Year"],
        #         uploaded_by=user,
        #         filename=file.filename
        #     )db.

    db_manager = core_utils.get_db_manager(UploadDataTimeDetails)
    db_manager.insert_upload_data_time_details_if_not_exists(meta_info["Month"], meta_info["Year"])
    return {"message": "File uploaded and data saved successfully."}
    # if Model:
    #     db_manager = core_utils.get_db_manager(Model)


    #     if file.filename.endswith('.xlsx') or file.filename.endswith('.xlsm'):
    #         contents = await file.read()
    #         pre_processor = PreProcessing(file_id)
    #         df = pre_processor.preprocess_file(io.BytesIO(contents))
    #         if file_id == 'forecast':
    #             db_manager_forecast = core_utils.get_db_manager(ForecastMonthsModel)
    #             forecast_month = pre_processor.month_codes
    #             forecast_month['UploadedFile'] = file.filename
    #             forecast_month['CreatedBy'] = user

    #             forecast_month_df = pd.DataFrame([forecast_month])
    #             db_manager_forecast.save_to_db(forecast_month_df)



    #     else:
    #         raise HTTPException(status_code=400, detail="Invalid file type.")
    # else:
    #     raise HTTPException(status_code=400, detail="Unknown file_id")
    # month_year = pre_processor.get_month_year(file.filename)
    # if month_year:
    #     df['Month'] = month_year['Month']
    #     df['Year'] = month_year['Year']
    # else:
    #     raise HTTPException(status_code=400, detail="File does not have a month_year(MMMM_YYYY).")
    # df.columns = df.columns.str.strip()
    # df['CreatedBy'] = user
    # df['UpdatedBy'] = user
    # df['UploadedFile'] = file.filename

    # db_manager.save_to_db(df)


    # return {"message": "File uploaded and data saved."}

@app.get("/records/{file_id}")
def get_records(
    file_id: str,
    skip: int = 0,
    limit: int = 10,
    search: str = None,
    searchable_field: str = None,
    global_filter: str = None,
    select_columns: List[str] = None,
    month: str = None,
    year: int = None,
    main_lob: str = None,
    case_type: str = None,
    forecast_month: str = None
):
    """
    Retrieve records by file_id (roster, skilling, forecast, etc.)
    """
    try:
        Model = get_model_or_all_models(file_id)
    except HTTPException as e:
        raise e
    db_manager = core_utils.get_db_manager(Model, limit, skip, select_columns)

    # ======================= FORECAST =============================
    if file_id == 'forecast':
        # Use custom search for forecast (multi-field)
        if main_lob or case_type:
            data = db_manager.search_db(
                searchable_fields=['Centene_Capacity_Plan_Main_LOB', 'Centene_Capacity_Plan_Case_Type'],
                keywords=[main_lob, case_type],
                month=month,
                year=year
            )
        elif (search and searchable_field):
            try:
                data = db_manager.search_db(searchable_field, search, month=month, year=year)
            except InValidSearchException as e:
                raise HTTPException(status_code=500, detail=e)
        elif global_filter:
            try:
                data = db_manager.global_search_db(global_filter, month, year)
            except InValidSearchException as e:
                raise HTTPException(status_code=500, detail=e)
        else:
            data = db_manager.read_db(month, year)

        # Perform post-processing
        post_processor = PostProcessing(core_utils=core_utils)
        tabs = post_processor.forecast_tabs(month, year)
        result = {'total': data['total']}
        processed_data = [post_processor.forecast_schema(tabs, d) for d in data['records']]

        if forecast_month:
            processed_data = post_processor.forecast_month_data(processed_data, forecast_month)

        result['data'] = processed_data
        return result

    # ======================= ROSTER / SKILLING / OTHERS =============================
    else:
        try:
            if (search and searchable_field):
                data = db_manager.search_db(searchable_field, search, month=month, year=year)
            elif global_filter:
                data = db_manager.global_search_db(global_filter, month, year)
            else:
                data = db_manager.read_db(month, year)

        except InValidSearchException as e:
            raise HTTPException(status_code=500, detail=e)

        return data


@app.get("/table/summary/{summary_type}")
def get_summary_table(
    summary_type: str,
    month: str,
    year: int,
):
    """
    Returns a table as HTML response
    if no data available returns error response
    """
    if not summary_type or not month or not year:
        raise HTTPException(400, detail="missing input parameters")
    df = get_summary_data_by_summary_type(month, year, summary_type)
    if df.empty:
        raise HTTPException(404, detail="No data available for the given month and year")
    # Convert DataFrame to HTML
    html_table = df.to_html(index=False, border=1, justify='center')
    return HTMLResponse(content=html_table, status_code=200)

@app.get("/record_history/")
@app.get("/record_history/{file_id}")
def get_record_history(
    file_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 10,
):
    RecordModel = get_model_or_all_models(file_id)
    if RecordModel is None:
        raise HTTPException(status_code=404, detail="Model not found")

    if file_id.lower() != 'all':
        db_manager = core_utils.get_db_manager(RecordModel,skip=skip, limit=limit, select_columns=['CreatedBy','CreatedDateTime', 'UploadedFile'])
        result = insert_file_id(db_manager, file_id)
    else:
        result = {'total': 0, 'records': []}
        # Iterate through all models and collect results
        for key in RecordModel.keys():
            db_manager = core_utils.get_db_manager(RecordModel[key],skip=skip, limit=limit, select_columns=['CreatedBy','CreatedDateTime', 'UploadedFile'])
            model_result = insert_file_id(db_manager, key)
            result['total'] += model_result['total']
            result['records'].extend(model_result['records'])
    return result


@app.get("/model_schema/{file_id}")
def get_model_schema(file_id, month:str, year:int, main_lob:str=None, case_type:str=None):
    Model = get_model_or_all_models(file_id)
    if not Model:
        raise HTTPException(status_code=404, detail="Model not found")
    db_manager = core_utils.get_db_manager(Model, limit = 1, skip = 0, select_columns=PreProcessing(file_id).MAPPING[file_id])
    if file_id == 'forecast':

        post_processor = PostProcessing(core_utils=core_utils)
        tabs = post_processor.forecast_tabs(month, year)
        summation_data:Dict[str, int]|None = None
        if main_lob or case_type:
            data = db_manager.search_db(['Centene_Capacity_Plan_Main_LOB', 'Centene_Capacity_Plan_Case_Type'], [main_lob, case_type], month, year)
            summation_data = db_manager.sum_metrics(month, year, main_lob, case_type)
        else:
            data = db_manager.read_db(month, year)
        data = post_processor.forecast_schema(tabs, data)
        if summation_data:
            totals = post_processor.forecast_totals(tabs, summation_data)
            return {'tab':tabs, 'schema':data, 'totals':totals}
        return {'tab':tabs, 'schema':data}
    elif file_id in ['roster', 'prod_team_roster']:
        exclude_fields = {"CreatedBy", "CreatedDateTime", "UpdatedBy", "UpdatedDateTime", "UploadedFile", "id"}
        schema = []

        data = db_manager.read_db(month, year)
        logger.debug(f"Schema data: {data['records'][0]}")
        for field in data['records'][0]:
            if field not in exclude_fields:
                schema.append(
                    {
                        "data": field,
                        "title": to_title_case(field)
                    }
                )
        return {'schema':schema}

    else:
        raise HTTPException(status_code=404, detail="Model not found")

@app.get("/metadata/months_years")
def get_months_years_dropdowns():
    """
    Returns available months and years from UploadDataTimeDetails table
    Structure: {"months": [...], "years": [...]}
    """

    return {'data': get_month_and_year_dropdown()}


@app.get("/download_file/{file_id}")
def download(
    file_id,
    month:str = None,
    year:int = None,
    ):
    if file_id == "summary":
        # folder_path = os.path.join(BASE_DIR, "logics", "data", "constants", "medicare_medicaid_summary")
        try:
            output = get_combined_summary_excel(month, year)
            return StreamingResponse(
                output,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": "attachment; filename=output.xlsx"}
            )
        except ValueError as ve:
            raise HTTPException(status_code=404, detail=str(ve))
    Model = get_model_or_all_models(file_id)
    if Model:
        preprocessor = PreProcessing(file_id)
        select_columns = preprocessor.MAPPING[file_id]
        db_manager = core_utils.get_db_manager(Model, limit=1, skip=0)
        total = db_manager.get_totals()
        # select_columns.append('UploadedFile')
        db_manager = core_utils.get_db_manager(Model, limit=total, skip=0, select_columns=select_columns)
        df = db_manager.download_db(month, year)
        if df.empty:
            raise HTTPException(status_code=404, detail="No data available for the given month and year")
        post_processor = PostProcessing(core_utils=core_utils)
        create_index = False
        if file_id == 'forecast':
            try:
                output=download_forecast_excel(month, year)
                return StreamingResponse(
                    output,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=output.xlsx"}
                )
            except ValueError as e:
                logger.error(f"Data not found - {e}")
                return HTTPException(404, detail=e)


        df.columns = post_processor.MAPPING[file_id]
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=create_index)
        output.seek(0)

        # Return as Excel file
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=output.xlsx"}
        )
    else:
        raise HTTPException(status_code=404, detail="Model not found")


# ==================== MANAGER VIEW ENDPOINTS ====================

@app.get("/api/manager-view/filters")
def get_manager_view_filters():
    """
    GET /api/manager-view/filters

    Returns dropdown options for Report Month and Category filters.
    Response includes available report months and category list from config.
    Cached for 5 minutes.
    """
    cache_key = "filters:v1"

    # Check cache first
    cached_response = filters_cache.get(cache_key)
    if cached_response is not None:
        logger.debug("[ManagerView] Returning cached filters response")
        return cached_response

    try:
        # Get available report months from database
        db_manager = core_utils.get_db_manager(UploadDataTimeDetails, limit=1000, skip=0, select_columns=None)
        report_months = get_available_report_months(db_manager)

        # Get categories from config
        categories = get_category_list()

        response = {
            "success": True,
            "report_months": report_months,
            "categories": categories,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Cache the response
        filters_cache.set(cache_key, response)

        logger.info(f"[ManagerView] Filters endpoint: {len(report_months)} months, {len(categories)} categories")
        return response

    except Exception as e:
        logger.error(f"[ManagerView] Error in filters endpoint: {e}", exc_info=True)
        return {
            "success": False,
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@app.get("/api/manager-view/data")
def get_manager_view_data(report_month: str, category: Optional[str] = None):
    """
    GET /api/manager-view/data

    Returns hierarchical category tree with metrics for the selected month/category.

    Query Parameters:
        - report_month (required): YYYY-MM format (e.g., "2025-02")
        - category (optional): Category ID to filter. Empty/omitted = All Categories

    Response includes:
        - Hierarchical category tree with metrics (cf, hc, cap, gap) per month
        - 6 forecast months starting from report_month

    Cached for 60 seconds per unique (report_month, category) combination.
    """
    # Generate cache key
    category_key = category if category else "all"
    cache_key = f"data:v1:{report_month}:{category_key}"

    # Check cache first
    cached_response = data_cache.get(cache_key)
    if cached_response is not None:
        logger.debug(f"[ManagerView] Returning cached data response for {cache_key}")
        return cached_response

    try:
        # Validate report_month format (YYYY-MM)
        month_pattern = r'^\d{4}-(0[1-9]|1[0-2])$'
        if not re.match(month_pattern, report_month):
            return {
                "success": False,
                "error": "Invalid report_month (expected YYYY-MM).",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Parse report_month to get month name and year
        year = int(report_month.split('-')[0])
        month_num = int(report_month.split('-')[1])
        from calendar import month_name as cal_month_name
        month_name_str = list(cal_month_name)[month_num]

        # Get forecast months from database
        db_manager_forecast_months = core_utils.get_db_manager(ForecastMonthsModel, limit=1000, skip=0, select_columns=None)
        forecast_months = get_forecast_months_from_db(db_manager_forecast_months, month_name_str, year)

        if not forecast_months:
            logger.warning(f"[ManagerView] No forecast months found for {month_name_str} {year}")
            # Return empty response
            return {
                "success": True,
                "report_month": report_month,
                "months": [],
                "categories": [],
                "category_name": "All Categories" if not category else category,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Get forecast records from database
        db_manager_forecast = core_utils.get_db_manager(ForecastModel, limit=100000, skip=0, select_columns=None)
        data = db_manager_forecast.read_db(month_name_str, year)
        records = data.get("records", [])

        if not records:
            logger.warning(f"[ManagerView] No forecast records found for {month_name_str} {year}")
            return {
                "success": True,
                "report_month": report_month,
                "months": forecast_months,
                "categories": [],
                "category_name": "All Categories" if not category else category,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Build category tree
        categories_tree = build_category_tree(records, forecast_months, category_filter=category)

        # Get category name
        if category:
            category_list = get_category_list()
            category_name = next((cat["display"] for cat in category_list if cat["value"] == category), "Unknown Category")

            # Check if category exists
            if not categories_tree:
                return {
                    "success": False,
                    "error": f"Unknown category id: {category}",
                    "status_code": 404,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
        else:
            category_name = "All Categories"

        response = {
            "success": True,
            "report_month": report_month,
            "months": forecast_months,
            "categories": categories_tree,
            "category_name": category_name,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Cache the response
        data_cache.set(cache_key, response)

        logger.info(f"[ManagerView] Data endpoint: {report_month}, category={category}, {len(categories_tree)} categories")
        return response

    except Exception as e:
        logger.error(f"[ManagerView] Error in data endpoint: {e}", exc_info=True)
        return {
            "success": False,
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@app.get("/api/manager-view/debug/categorization")
def debug_record_categorization_endpoint(
    report_month: str,
    main_lob: Optional[str] = None,
    state: Optional[str] = None,
    case_type: Optional[str] = None
):
    """
    GET /api/manager-view/debug/categorization

    **QA/DEBUG ENDPOINT**

    Returns detailed diagnostics showing why a record matched or didn't match each category.
    Helps analysts quickly identify why records aren't classifying as expected.

    Query Parameters:
        - report_month (required): YYYY-MM format (e.g., "2025-02")
        - main_lob (optional): Main LOB value to test
        - state (optional): State value to test
        - case_type (optional): Case type value to test

    Response includes for each category:
        - category_id, category_name, category_path
        - is_match: boolean indicating if the record matches
        - matched_fields: fields that matched with actual vs expected values
        - unmatched_fields: fields that didn't match with actual vs expected values
        - rule counts: total_rules, matched_rules, unmatched_rules
    """
    try:
        # Validate report_month format
        month_pattern = r'^\d{4}-(0[1-9]|1[0-2])$'
        if not re.match(month_pattern, report_month):
            return {
                "success": False,
                "error": "Invalid report_month (expected YYYY-MM).",
                "status_code": 400,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Build a test record
        test_record = {
            "Centene_Capacity_Plan_Main_LOB": main_lob or "",
            "Centene_Capacity_Plan_State": state or "",
            "Centene_Capacity_Plan_Case_Type": case_type or ""
        }

        # Run diagnostics
        diagnostics = diagnose_record_categorization(test_record)

        response = {
            "success": True,
            "report_month": report_month,
            "test_record": {
                "main_lob": main_lob,
                "state": state,
                "case_type": case_type
            },
            "diagnostics": diagnostics,
            "summary": {
                "total_categories": len(diagnostics),
                "matched_categories": sum(1 for d in diagnostics if d["is_match"]),
                "unmatched_categories": sum(1 for d in diagnostics if not d["is_match"])
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        logger.info(f"[ManagerView Debug] Categorization check: {len(diagnostics)} categories analyzed")
        return response

    except Exception as e:
        logger.error(f"[ManagerView Debug] Error in categorization endpoint: {e}", exc_info=True)
        return {
            "success": False,
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


# ==================== CASCADE FILTER ENDPOINTS ====================

@app.get("/forecast/filter-years")
def get_forecast_filter_years():
    """
    GET /forecast/filter-years

    Returns all years that have forecast data available.

    Response:
        {"years": [{"value": "2025", "display": "2025"}, ...]}

    Cached for 5 minutes.
    """
    cache_key = generate_cascade_cache_key("cascade:years")

    # Check cache first
    cached_response = filters_cache.get(cache_key)
    if cached_response is not None:
        logger.debug("[Cascade] Returning cached years response")
        return cached_response

    try:
        # Get distinct years from ForecastModel
        db_manager = core_utils.get_db_manager(ForecastModel, limit=100000, skip=0, select_columns=["Year"])
        data = db_manager.read_db()
        records = data.get("records", [])

        # Extract unique years
        years_set = set()
        for record in records:
            year = record.get("Year")
            if year:
                years_set.add(year)

        # Sort in descending order (newest first)
        sorted_years = sorted(list(years_set), reverse=True)

        # Format response
        years_list = [{"value": str(year), "display": str(year)} for year in sorted_years]
        response = {"years": years_list}

        # Cache the response
        filters_cache.set(cache_key, response)

        logger.info(f"[Cascade] Filter years endpoint: {len(years_list)} years found")
        return response

    except Exception as e:
        logger.error(f"[Cascade] Error in filter-years endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve available years")


@app.get("/forecast/months/{year}")
def get_forecast_months_for_year(year: int):
    """
    GET /forecast/months/{year}

    Returns available months for the selected year based on data availability.

    Path Parameters:
        year: Selected year (e.g., 2025)

    Response:
        [{"value": "1", "display": "January"}, {"value": "2", "display": "February"}, ...]

    Cached for 5 minutes.
    """
    # Validate year
    if year < 2020 or year > 2100:
        raise HTTPException(status_code=400, detail=f"Invalid year: {year}")

    cache_key = generate_cascade_cache_key("cascade:months", year=year)

    # Check cache first
    cached_response = filters_cache.get(cache_key)
    if cached_response is not None:
        logger.debug(f"[Cascade] Returning cached months response for year {year}")
        return cached_response

    try:
        # Get distinct months from ForecastModel for the given year
        db_manager = core_utils.get_db_manager(ForecastModel, limit=100000, skip=0, select_columns=["Month", "Year"])
        data = db_manager.read_db()
        records = data.get("records", [])

        # Extract unique months for this year
        from calendar import month_name as cal_month_name
        months_set = set()
        for record in records:
            if record.get("Year") == year:
                month_str = record.get("Month", "").strip()
                if month_str:
                    months_set.add(month_str)

        if not months_set:
            raise HTTPException(status_code=404, detail=f"No data available for year {year}")

        # Convert month names to numeric format and sort
        month_list = []
        for month_str in months_set:
            try:
                month_num = list(cal_month_name).index(month_str)
                month_list.append((month_num, month_str))
            except ValueError:
                logger.warning(f"[Cascade] Invalid month name found: {month_str}")
                continue

        # Sort by month number
        month_list.sort(key=lambda x: x[0])

        # Format response
        response = [{"value": str(num), "display": name} for num, name in month_list]

        # Cache the response
        filters_cache.set(cache_key, response)

        logger.info(f"[Cascade] Months endpoint: {len(response)} months found for year {year}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Cascade] Error in months endpoint for year {year}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve months for year {year}")


@app.get("/forecast/platforms")
def get_forecast_platforms(year: int, month: int):
    """
    GET /forecast/platforms

    Returns available platforms (BOC - Basis of Calculation) for selected year and month.

    Query Parameters:
        year: Selected year
        month: Selected month (1-12)

    Response:
        [{"value": "Amisys", "display": "Amisys"}, {"value": "Facets", "display": "Facets"}, ...]

    Cached for 5 minutes.
    """
    # Validate parameters
    if not year or not month:
        raise HTTPException(status_code=400, detail="Invalid parameters: year and month are required")
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Invalid month: must be 1-12")

    cache_key = generate_cascade_cache_key("cascade:platforms", year=year, month=month)

    # Check cache first
    cached_response = filters_cache.get(cache_key)
    if cached_response is not None:
        logger.debug(f"[Cascade] Returning cached platforms response for year={year}, month={month}")
        return cached_response

    try:
        # Convert month number to month name
        from calendar import month_name as cal_month_name
        month_name_str = list(cal_month_name)[month]

        # Get forecast records for the given year and month
        db_manager = core_utils.get_db_manager(
            ForecastModel,
            limit=100000,
            skip=0,
            select_columns=["Centene_Capacity_Plan_Main_LOB", "Month", "Year"]
        )
        data = db_manager.read_db(month_name_str, year)
        records = data.get("records", [])

        if not records:
            raise HTTPException(
                status_code=404,
                detail=f"No platforms found for year={year}, month={month}"
            )

        # Extract unique platforms
        platforms = extract_unique_cascade_values(records, "platform")

        if not platforms:
            raise HTTPException(
                status_code=404,
                detail=f"No platforms found for year={year}, month={month}"
            )

        # Format response
        response = [{"value": platform, "display": platform} for platform in platforms]

        # Cache the response
        filters_cache.set(cache_key, response)

        logger.info(f"[Cascade] Platforms endpoint: {len(response)} platforms found for {month_name_str} {year}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Cascade] Error in platforms endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve platforms")


@app.get("/forecast/markets")
def get_forecast_markets(year: int, month: int, platform: str):
    """
    GET /forecast/markets

    Returns available markets (insurance types) filtered by platform, year, and month.

    Query Parameters:
        year: Selected year
        month: Selected month (1-12)
        platform: Selected platform (e.g., "Amisys")

    Response:
        [{"value": "Medicaid", "display": "Medicaid"}, {"value": "Medicare", "display": "Medicare"}, ...]

    Cached for 5 minutes.
    """
    # Validate parameters
    if not year or not month or not platform:
        raise HTTPException(status_code=400, detail="Missing required parameters: year, month, platform")
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Invalid month: must be 1-12")

    cache_key = generate_cascade_cache_key("cascade:markets", year=year, month=month, platform=platform)

    # Check cache first
    cached_response = filters_cache.get(cache_key)
    if cached_response is not None:
        logger.debug(f"[Cascade] Returning cached markets response for year={year}, month={month}, platform={platform}")
        return cached_response

    try:
        # Convert month number to month name
        from calendar import month_name as cal_month_name
        month_name_str = list(cal_month_name)[month]

        # Get forecast records for the given year and month
        db_manager = core_utils.get_db_manager(
            ForecastModel,
            limit=100000,
            skip=0,
            select_columns=["Centene_Capacity_Plan_Main_LOB", "Month", "Year"]
        )
        data = db_manager.read_db(month_name_str, year)
        records = data.get("records", [])

        if not records:
            raise HTTPException(
                status_code=404,
                detail=f"No markets found for platform={platform}, year={year}, month={month}"
            )

        # Extract unique markets filtered by platform
        markets = extract_unique_cascade_values(records, "market", platform_filter=platform)

        if not markets:
            raise HTTPException(
                status_code=404,
                detail=f"No markets found for platform={platform}, year={year}, month={month}"
            )

        # Format response
        response = [{"value": market, "display": market} for market in markets]

        # Cache the response
        filters_cache.set(cache_key, response)

        logger.info(f"[Cascade] Markets endpoint: {len(response)} markets found for {platform} / {month_name_str} {year}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Cascade] Error in markets endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve markets")


@app.get("/forecast/localities")
def get_forecast_localities(year: int, month: int, platform: str, market: str):
    """
    GET /forecast/localities

    Returns available localities for selected platform and market.
    Always includes "-- All Localities --" as first option.

    Query Parameters:
        year: Selected year
        month: Selected month (1-12)
        platform: Selected platform
        market: Selected market

    Response:
        [
            {"value": "", "display": "-- All Localities --"},
            {"value": "DOMESTIC", "display": "Domestic"},
            {"value": "OFFSHORE", "display": "Offshore"}
        ]

    Cached for 5 minutes.
    """
    # Validate parameters
    if not year or not month or not platform or not market:
        raise HTTPException(status_code=400, detail="Missing required parameters: year, month, platform, market")
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Invalid month: must be 1-12")

    cache_key = generate_cascade_cache_key("cascade:localities", year=year, month=month, platform=platform, market=market)

    # Check cache first
    cached_response = filters_cache.get(cache_key)
    if cached_response is not None:
        logger.debug(f"[Cascade] Returning cached localities response")
        return cached_response

    try:
        # Convert month number to month name
        from calendar import month_name as cal_month_name
        month_name_str = list(cal_month_name)[month]

        # Get forecast records for the given year and month
        db_manager = core_utils.get_db_manager(
            ForecastModel,
            limit=100000,
            skip=0,
            select_columns=["Centene_Capacity_Plan_Main_LOB", "Month", "Year"]
        )
        data = db_manager.read_db(month_name_str, year)
        records = data.get("records", [])

        if not records:
            raise HTTPException(status_code=404, detail="No localities found for given filters")

        # Extract unique localities filtered by platform and market
        localities = extract_unique_cascade_values(
            records, "locality",
            platform_filter=platform,
            market_filter=market
        )

        # Always include "All Localities" option as first item
        response = [{"value": "", "display": "-- All Localities --"}]

        # Add found localities
        for locality in localities:
            response.append({"value": locality, "display": locality})

        # Cache the response
        filters_cache.set(cache_key, response)

        logger.info(f"[Cascade] Localities endpoint: {len(response)-1} localities found (+ All option)")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Cascade] Error in localities endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve localities")


@app.get("/forecast/worktypes")
def get_forecast_worktypes(
    year: int,
    month: int,
    platform: str,
    market: str,
    locality: Optional[str] = None
):
    """
    GET /forecast/worktypes

    Returns available worktypes (processes) for selected filters. This is the final step in the cascade.

    Query Parameters:
        year: Selected year
        month: Selected month (1-12)
        platform: Selected platform
        market: Selected market
        locality: Selected locality (optional - empty string or None = all localities)

    Response:
        [
            {"value": "Claims Processing", "display": "Claims Processing"},
            {"value": "Enrollment", "display": "Enrollment"},
            ...
        ]

    Cached for 5 minutes.
    """
    # Validate parameters
    if not year or not month or not platform or not market:
        raise HTTPException(status_code=400, detail="Missing required parameters: year, month, platform, market")
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Invalid month: must be 1-12")

    # Normalize locality (empty string or None both mean "all localities")
    locality_normalized = locality if locality else None

    cache_key = generate_cascade_cache_key(
        "cascade:worktypes",
        year=year,
        month=month,
        platform=platform,
        market=market,
        locality=locality_normalized
    )

    # Check cache first
    cached_response = filters_cache.get(cache_key)
    if cached_response is not None:
        logger.debug(f"[Cascade] Returning cached worktypes response")
        return cached_response

    try:
        # Convert month number to month name
        from calendar import month_name as cal_month_name
        month_name_str = list(cal_month_name)[month]

        # Get forecast records for the given year and month
        db_manager = core_utils.get_db_manager(
            ForecastModel,
            limit=100000,
            skip=0,
            select_columns=["Centene_Capacity_Plan_Main_LOB", "Centene_Capacity_Plan_Case_Type", "Month", "Year"]
        )
        data = db_manager.read_db(month_name_str, year)
        records = data.get("records", [])

        if not records:
            raise HTTPException(status_code=404, detail="No worktypes found for given filters")

        # Filter records by platform, market, and optionally locality
        filtered_records = []
        for record in records:
            main_lob = record.get("Centene_Capacity_Plan_Main_LOB", "")
            if not main_lob:
                continue

            parsed = parse_main_lob_preserve_case(main_lob)

            # Check platform match (case-insensitive)
            if not parsed.get("platform") or parsed["platform"].lower() != platform.lower():
                continue

            # Check market match (case-insensitive)
            if not parsed.get("market") or parsed["market"].lower() != market.lower():
                continue

            # Check locality match if specified (case-insensitive)
            if locality_normalized:
                if not parsed.get("locality") or parsed["locality"].lower() != locality_normalized.lower():
                    continue

            filtered_records.append(record)

        # Extract unique worktypes from filtered records
        worktypes_set = set()
        for record in filtered_records:
            worktype = record.get("Centene_Capacity_Plan_Case_Type", "").strip()
            if worktype:
                worktypes_set.add(worktype)

        if not worktypes_set:
            raise HTTPException(status_code=404, detail="No worktypes found for given filters")

        # Sort and format response
        sorted_worktypes = sorted(list(worktypes_set))
        response = [{"value": worktype, "display": worktype} for worktype in sorted_worktypes]

        # Cache the response
        filters_cache.set(cache_key, response)

        logger.info(f"[Cascade] Worktypes endpoint: {len(response)} worktypes found")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Cascade] Error in worktypes endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve worktypes")