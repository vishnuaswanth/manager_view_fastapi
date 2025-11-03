"""
File upload, download, and management endpoints.

Handles:
- File upload for forecast, roster, and other data files
- Record retrieval with search and filtering
- Upload history tracking
- Model schema information
- File download functionality
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, HTMLResponse
from typing import List, Optional
import pandas as pd
import io
import logging

from code.logics.core_utils import (
    get_model_or_all_models,
    PreProcessing,
    PostProcessing,
    insert_file_id,
    to_title_case
)
from code.logics.export_utils import (
    get_combined_summary_excel,
    get_summary_data_by_summary_type,
    get_month_and_year_dropdown,
    download_forecast_excel
)
from code.logics.allocation import process_files
from code.logics.db import (
    InValidSearchException,
    ForecastMonthsModel,
    RawData,
    UploadDataTimeDetails
)
from code.api.dependencies import get_core_utils, get_logger
from code.api.utils.responses import success_response, error_response
from code.api.utils.validators import validate_file_id
from code.settings import BASE_DIR

# Initialize router and dependencies
router = APIRouter()
logger = get_logger(__name__)
core_utils = get_core_utils()


def invalidate_forecast_cache(month: str, year: int):
    """
    Invalidate all forecast-related caches.

    Called when a new forecast file is uploaded to clear all dependent caches:
    - Manager view filters cache (available months, categories)
    - Manager view data cache (hierarchical category trees)
    - Forecast cascade filters cache (years, months, platforms, markets, localities, worktypes)

    This ensures users see fresh data after upload without waiting for TTL expiration.

    Args:
        month: Month name (e.g., "January") - for logging only
        year: Year number (e.g., 2025) - for logging only
    """
    try:
        from code.cache import clear_all_caches
        result = clear_all_caches()
        logger.info(f"[Cache] Cleared all caches due to forecast upload for {month} {year}: {result}")
    except Exception as e:
        logger.error(f"[Cache] Error invalidating caches for {month} {year}: {e}", exc_info=True)


@router.get("/")
def health_check():
    """Root endpoint - health check."""
    return success_response(message="Centene forecasting API")


@router.post("/upload/{file_id}")
async def upload_file(
    file_id: str,
    user: str,
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None
):
    """
    Upload and process data files (forecast, roster, etc.).

    Path Parameters:
        file_id: Type of file being uploaded (forecast, prod_team_roster, upload_roster, etc.)

    Query Parameters:
        user: Username of the person uploading

    Request Body:
        file: Excel or CSV file

    Responses:
        200: File uploaded successfully
        400: Invalid file type or format
        500: Processing error

    Processing:
        - Validates file type and extracts month/year from filename
        - Preprocesses data based on file type
        - Saves to database
        - For forecast: triggers background allocation processing
        - Invalidates relevant caches
    """
    Model = get_model_or_all_models(file_id)

    if not Model:
        raise HTTPException(
            status_code=400,
            detail=error_response("Unknown file_id", {"file_id": file_id})
        )

    if not file.filename.endswith(('.xlsx', '.xlsm', '.csv')):
        raise HTTPException(
            status_code=400,
            detail=error_response("Invalid file type. Expected .xlsx, .xlsm, or .csv")
        )

    contents = await file.read()
    pre_processor = PreProcessing(file_id)
    month_year = pre_processor.get_month_year(file.filename)

    if not month_year:
        raise HTTPException(
            status_code=400,
            detail=error_response(
                "Filename must contain month and year",
                {"example": "forecast_Jan_2024.xlsx or roster_January-2024.xlsx"}
            )
        )

    meta_info = {
        "Month": month_year["Month"],
        "Year": int(month_year["Year"]),
        "CreatedBy": user,
        "UpdatedBy": user,
        "UploadedFile": file.filename
    }

    # ============= UPLOAD_ROSTER: Process both Roster and Skilling sheets =============
    if file_id == "upload_roster":
        try:
            excel_io = io.BytesIO(contents)
            sheets = pd.read_excel(excel_io, sheet_name=["Roster", "Skilling"])

            # Process Roster sheet
            roster_df = pre_processor.preprocess_roster(sheets["Roster"])
            for col, val in meta_info.items():
                roster_df[col] = val
            db_manager_roster = core_utils.get_db_manager(Model["Roster"])
            db_manager_roster.save_to_db(roster_df, replace=True)

            # Process Skilling sheet
            skilling_df = pre_processor.preprocess_skilling(sheets["Skilling"])
            for col, val in meta_info.items():
                skilling_df[col] = val
            db_manager_skilling = core_utils.get_db_manager(Model["Skilling"])
            db_manager_skilling.save_to_db(skilling_df, replace=True)

        except Exception as e:
            logger.error(f"Error processing roster file: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=error_response("Error processing roster file", str(e))
            )

    # ============= FORECAST: Process and trigger allocation =============
    elif file_id == "forecast":
        try:
            dfs = pre_processor.process_forecast_file(io.BytesIO(contents))
        except ValueError as ve:
            logger.error(f"Error processing forecast file: {ve}")
            raise HTTPException(
                status_code=400,
                detail=error_response("Invalid forecast file format", str(ve))
            )
        except Exception as e:
            logger.error(f"Unexpected error processing forecast file: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=error_response("Error processing forecast file")
            )

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
                    logger.info(f"Processed Data Model: {data_model} | Type: {data_model_type}")

            db_manager = core_utils.get_db_manager(RawData)
            db_manager.bulk_save_raw_data_with_history(items)
        except Exception as e:
            logger.error(f"Error updating raw data: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=error_response("Error saving forecast data to database")
            )

        try:
            db_manager_forecast = core_utils.get_db_manager(ForecastMonthsModel)
            forecast_meta = pre_processor.month_codes
            forecast_meta["UploadedFile"] = file.filename
            forecast_meta["CreatedBy"] = user
            forecast_df = pd.DataFrame([forecast_meta])
            db_manager_forecast.save_to_db(forecast_df)
        except Exception as e:
            logger.error(f"Error updating forecast months: {e}", exc_info=True)

        # Trigger background allocation processing
        background_tasks.add_task(
            process_files,
            data_month=month_year["Month"],
            data_year=int(month_year["Year"]),
            forecast_file_uploaded_by=user,
            forecast_filename=file.filename
        )

        # Invalidate cache
        invalidate_forecast_cache(month_year["Month"], int(month_year["Year"]))

    # ============= OTHER FILES: Generic preprocessing =============
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

    # Track upload time
    db_manager = core_utils.get_db_manager(UploadDataTimeDetails)
    db_manager.insert_upload_data_time_details_if_not_exists(
        meta_info["Month"],
        meta_info["Year"]
    )

    return success_response(message="File uploaded and data saved successfully")


@router.get("/records/{file_id}")
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
    Retrieve records by file type with search and filtering.

    Path Parameters:
        file_id: Type of data to retrieve (forecast, roster, prod_team_roster, etc.)

    Query Parameters:
        skip: Pagination offset (default: 0)
        limit: Max records to return (default: 10)
        search: Search keyword
        searchable_field: Field to search in
        global_filter: Global search across all fields
        select_columns: Specific columns to return
        month: Filter by month
        year: Filter by year
        main_lob: Filter by Main LOB (forecast only)
        case_type: Filter by Case Type (forecast only)
        forecast_month: Specific forecast month column to extract

    Returns:
        {
            "total": 150,
            "data": [...]
        }
    """
    try:
        Model = get_model_or_all_models(file_id)
    except HTTPException as e:
        raise e

    db_manager = core_utils.get_db_manager(Model, limit, skip, select_columns)

    # ============= FORECAST: Special handling with post-processing =============
    if file_id == 'forecast':
        # Search with filters
        if main_lob or case_type:
            data = db_manager.search_db(
                searchable_fields=['Centene_Capacity_Plan_Main_LOB', 'Centene_Capacity_Plan_Case_Type'],
                keywords=[main_lob, case_type],
                month=month,
                year=year
            )
        elif search and searchable_field:
            try:
                data = db_manager.search_db(searchable_field, search, month=month, year=year)
            except InValidSearchException as e:
                raise HTTPException(status_code=500, detail=error_response(str(e)))
        elif global_filter:
            try:
                data = db_manager.global_search_db(global_filter, month, year)
            except InValidSearchException as e:
                raise HTTPException(status_code=500, detail=error_response(str(e)))
        else:
            data = db_manager.read_db(month, year)

        # Post-process forecast data
        post_processor = PostProcessing(core_utils=core_utils)
        tabs = post_processor.forecast_tabs(month, year)
        result = {'total': data['total']}
        processed_data = [post_processor.forecast_schema(tabs, d) for d in data['records']]

        if forecast_month:
            processed_data = post_processor.forecast_month_data(processed_data, forecast_month)

        result['data'] = processed_data
        return result

    # ============= OTHER FILES: Standard retrieval =============
    else:
        try:
            if search and searchable_field:
                data = db_manager.search_db(searchable_field, search, month=month, year=year)
            elif global_filter:
                data = db_manager.global_search_db(global_filter, month, year)
            else:
                data = db_manager.read_db(month, year)
        except InValidSearchException as e:
            raise HTTPException(status_code=500, detail=error_response(str(e)))

        return data


@router.get("/table/summary/{summary_type}")
def get_summary_table(summary_type: str, month: str, year: int):
    """
    Get summary table as HTML.

    Path Parameters:
        summary_type: Type of summary to retrieve

    Query Parameters:
        month: Month name
        year: Year number

    Returns:
        HTML table response
    """
    if not summary_type or not month or not year:
        raise HTTPException(
            status_code=400,
            detail=error_response("Missing required parameters: summary_type, month, year")
        )

    df = get_summary_data_by_summary_type(month, year, summary_type)

    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=error_response("No data available for the given month and year")
        )

    html_table = df.to_html(index=False, border=1, justify='center')
    return HTMLResponse(content=html_table, status_code=200)


@router.get("/record_history/")
@router.get("/record_history/{file_id}")
def get_record_history(
    file_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 10
):
    """
    Get upload history for files.

    Path Parameters:
        file_id: Specific file type or "all" (optional)

    Query Parameters:
        skip: Pagination offset (default: 0)
        limit: Max records to return (default: 10)

    Returns:
        {
            "total": 50,
            "records": [
                {
                    "file_id": "Forecast",
                    "CreatedBy": "user123",
                    "CreatedDateTime": "2025-01-15T10:30:00",
                    "UploadedFile": "forecast_Jan_2025.xlsx"
                },
                ...
            ]
        }
    """
    RecordModel = get_model_or_all_models(file_id)

    if RecordModel is None:
        raise HTTPException(
            status_code=404,
            detail=error_response("Model not found", {"file_id": file_id})
        )

    if file_id and file_id.lower() != 'all':
        db_manager = core_utils.get_db_manager(
            RecordModel,
            skip=skip,
            limit=limit,
            select_columns=['CreatedBy', 'CreatedDateTime', 'UploadedFile']
        )
        result = insert_file_id(db_manager, file_id)
    else:
        result = {'total': 0, 'records': []}
        # Iterate through all models and collect results
        for key in RecordModel.keys():
            db_manager = core_utils.get_db_manager(
                RecordModel[key],
                skip=skip,
                limit=limit,
                select_columns=['CreatedBy', 'CreatedDateTime', 'UploadedFile']
            )
            model_result = insert_file_id(db_manager, key)
            result['total'] += model_result['total']
            result['records'].extend(model_result['records'])

    return result


@router.get("/model_schema/{file_id}")
def get_model_schema(
    file_id: str,
    month: str,
    year: int,
    main_lob: str = None,
    case_type: str = None
):
    """
    Get schema/column structure for a model.

    Path Parameters:
        file_id: Type of model (forecast, roster, prod_team_roster, etc.)

    Query Parameters:
        month: Month name
        year: Year number
        main_lob: Filter by Main LOB (forecast only)
        case_type: Filter by Case Type (forecast only)

    Returns:
        For forecast:
        {
            "tab": {...},
            "schema": {...},
            "totals": {...}  # If main_lob/case_type provided
        }

        For roster:
        {
            "schema": [
                {"data": "field_name", "title": "Field Name"},
                ...
            ]
        }
    """
    Model = get_model_or_all_models(file_id)

    if not Model:
        raise HTTPException(
            status_code=404,
            detail=error_response("Model not found", {"file_id": file_id})
        )

    db_manager = core_utils.get_db_manager(
        Model,
        limit=1,
        skip=0,
        select_columns=PreProcessing(file_id).MAPPING[file_id]
    )

    if file_id == 'forecast':
        post_processor = PostProcessing(core_utils=core_utils)
        tabs = post_processor.forecast_tabs(month, year)
        summation_data = None

        if main_lob or case_type:
            data = db_manager.search_db(
                ['Centene_Capacity_Plan_Main_LOB', 'Centene_Capacity_Plan_Case_Type'],
                [main_lob, case_type],
                month,
                year
            )
            summation_data = db_manager.sum_metrics(month, year, main_lob, case_type)
        else:
            data = db_manager.read_db(month, year)

        data = post_processor.forecast_schema(tabs, data)

        if summation_data:
            totals = post_processor.forecast_totals(tabs, summation_data)
            return {'tab': tabs, 'schema': data, 'totals': totals}

        return {'tab': tabs, 'schema': data}

    elif file_id in ['roster', 'prod_team_roster']:
        exclude_fields = {
            "CreatedBy", "CreatedDateTime", "UpdatedBy",
            "UpdatedDateTime", "UploadedFile", "id"
        }
        schema = []

        data = db_manager.read_db(month, year)
        logger.debug(f"Schema data: {data['records'][0]}")

        for field in data['records'][0]:
            if field not in exclude_fields:
                schema.append({
                    "data": field,
                    "title": to_title_case(field)
                })

        return {'schema': schema}

    else:
        raise HTTPException(
            status_code=404,
            detail=error_response("Schema not available for this file type")
        )


@router.get("/metadata/months_years")
def get_months_years_dropdowns():
    """
    Get available months and years from uploaded data.

    Returns:
        {
            "data": {
                "months": ["January", "February", ...],
                "years": [2024, 2025, ...]
            }
        }
    """
    return {'data': get_month_and_year_dropdown()}


@router.get("/download_file/{file_id}")
def download_file(
    file_id: str,
    month: str = None,
    year: int = None
):
    """
    Download data file as Excel.

    Path Parameters:
        file_id: Type of file to download (forecast, roster, summary, etc.)

    Query Parameters:
        month: Month name (required for most file types)
        year: Year number (required for most file types)

    Returns:
        Excel file download
    """
    if file_id == "summary":
        try:
            output = get_combined_summary_excel(month, year)
            return StreamingResponse(
                output,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": "attachment; filename=summary_output.xlsx"}
            )
        except ValueError as ve:
            raise HTTPException(status_code=404, detail=error_response(str(ve)))

    Model = get_model_or_all_models(file_id)

    if not Model:
        raise HTTPException(
            status_code=404,
            detail=error_response("Model not found", {"file_id": file_id})
        )

    preprocessor = PreProcessing(file_id)
    select_columns = preprocessor.MAPPING[file_id]
    db_manager = core_utils.get_db_manager(Model, limit=1, skip=0)
    total = db_manager.get_totals()

    db_manager = core_utils.get_db_manager(
        Model,
        limit=total,
        skip=0,
        select_columns=select_columns
    )
    df = db_manager.download_db(month, year)

    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=error_response("No data available for the given month and year")
        )

    if file_id == 'forecast':
        try:
            output = download_forecast_excel(month, year)
            return StreamingResponse(
                output,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename=forecast_{month}_{year}.xlsx"}
            )
        except ValueError as e:
            logger.error(f"Forecast data not found: {e}")
            raise HTTPException(status_code=404, detail=error_response(str(e)))

    post_processor = PostProcessing(core_utils=core_utils)
    df.columns = post_processor.MAPPING[file_id]
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)

    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={file_id}_{month}_{year}.xlsx"}
    )
