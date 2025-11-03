"""
Allocation report download and execution tracking endpoints.

Provides endpoints for:
- Downloading allocation reports (bucket summary, bucket after allocation, roster allotment)
- Listing allocation execution history
- Getting detailed execution information
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import pandas as pd
import io
import logging
from typing import Optional

from code.logics.db import DBManager, AllocationReportsModel
from code.logics.allocation_tracker import list_executions, get_execution_by_id
from code.settings import MODE, SQLITE_DATABASE_URL, MSSQL_DATABASE_URL
from code.api.dependencies import get_logger
from code.api.utils.responses import success_response, error_response, paginated_response
from code.api.utils.validators import validate_month_year_pair, validate_pagination
from code.cache import (
    allocation_list_cache,
    allocation_detail_cache,
    generate_execution_list_cache_key,
    generate_execution_detail_cache_key,
    get_ttl_for_execution_status
)

# Determine database URL based on mode
if MODE.upper() == "DEBUG":
    DATABASE_URL = SQLITE_DATABASE_URL
elif MODE.upper() == "PRODUCTION":
    DATABASE_URL = MSSQL_DATABASE_URL
else:
    raise ValueError("Invalid MODE specified in config.")

# Initialize router and dependencies
router = APIRouter()
logger = get_logger(__name__)


@router.get("/download_allocation_report/bucket_summary")
def download_allocation_bucket_summary(month: str, year: int):
    """
    Download bucket summary allocation report as Excel file.

    Query Parameters:
        month: Month name (e.g., "January")
        year: Year number (e.g., 2025)

    Returns:
        Excel file with bucket summary data (Summary and Details sheets)

    Response Headers:
        Content-Disposition: attachment; filename=bucket_summary_{month}_{year}.xlsx
    """
    month, year = validate_month_year_pair(month, year)

    try:
        # Initialize DBManager
        db_manager = DBManager(
            database_url=DATABASE_URL,
            Model=AllocationReportsModel,
            limit=1000,
            skip=0,
            select_columns=None
        )

        # Retrieve report data
        df = db_manager.get_allocation_report_as_dataframes(month, year, 'bucket_summary')

        if df is None or df.empty:
            raise HTTPException(
                status_code=404,
                detail=error_response(f"No bucket_summary report found for {month} {year}")
            )

        # Split combined report back into Summary and Details
        summary_df = df[df['ReportSection'] == 'Summary'].drop(columns=['ReportSection'])
        details_df = df[df['ReportSection'] == 'Details'].drop(columns=['ReportSection'])

        # Create Excel file with two sheets
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            summary_df.to_excel(writer, sheet_name='Bucket_Summary', index=False)
            details_df.to_excel(writer, sheet_name='Vendor_Details', index=False)
        output.seek(0)

        filename = f"bucket_summary_{month}_{year}.xlsx"

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading bucket_summary report: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Failed to download report", str(e))
        )


@router.get("/download_allocation_report/bucket_after_allocation")
def download_allocation_bucket_after_allocation(month: str, year: int):
    """
    Download buckets after allocation report as Excel file.

    Query Parameters:
        month: Month name (e.g., "January")
        year: Year number (e.g., 2025)

    Returns:
        Excel file with allocation status per bucket

    Response Headers:
        Content-Disposition: attachment; filename=buckets_after_allocation_{month}_{year}.xlsx
    """
    month, year = validate_month_year_pair(month, year)

    try:
        # Initialize DBManager
        db_manager = DBManager(
            database_url=DATABASE_URL,
            Model=AllocationReportsModel,
            limit=1000,
            skip=0,
            select_columns=None
        )

        # Retrieve report data
        df = db_manager.get_allocation_report_as_dataframes(month, year, 'bucket_after_allocation')

        if df is None or df.empty:
            raise HTTPException(
                status_code=404,
                detail=error_response(f"No bucket_after_allocation report found for {month} {year}")
            )

        # Create Excel file
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)

        filename = f"buckets_after_allocation_{month}_{year}.xlsx"

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading bucket_after_allocation report: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Failed to download report", str(e))
        )


@router.get("/download_allocation_report/roster_allotment")
def download_allocation_roster_allotment(month: str, year: int):
    """
    Download roster allotment allocation report as Excel file.

    Query Parameters:
        month: Month name (e.g., "January")
        year: Year number (e.g., 2025)

    Returns:
        Excel file with vendor-level allocation details

    Response Headers:
        Content-Disposition: attachment; filename=roster_allotment_{month}_{year}.xlsx
    """
    month, year = validate_month_year_pair(month, year)

    try:
        # Initialize DBManager
        db_manager = DBManager(
            database_url=DATABASE_URL,
            Model=AllocationReportsModel,
            limit=1000,
            skip=0,
            select_columns=None
        )

        # Retrieve report data
        df = db_manager.get_allocation_report_as_dataframes(month, year, 'roster_allotment')

        if df is None or df.empty:
            raise HTTPException(
                status_code=404,
                detail=error_response(f"No roster_allotment report found for {month} {year}")
            )

        # Create Excel file
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)

        filename = f"roster_allotment_{month}_{year}.xlsx"

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading roster_allotment report: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Failed to download report", str(e))
        )


@router.get("/api/allocation/executions")
def list_allocation_executions(
    month: Optional[str] = None,
    year: Optional[int] = None,
    status: Optional[str] = None,
    uploaded_by: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """
    List allocation executions with minimal data for table view.

    Query Parameters:
        month: Filter by month (optional)
        year: Filter by year (optional)
        status: Filter by status (PENDING, IN_PROGRESS, SUCCESS, FAILED) (optional)
        uploaded_by: Filter by username (optional)
        limit: Maximum records to return (default: 50, max: 100)
        offset: Pagination offset (default: 0)

    Returns:
        {
            "success": true,
            "data": [
                {
                    "execution_id": "uuid-string",
                    "month": "January",
                    "year": 2025,
                    "status": "SUCCESS",
                    "start_time": "2025-01-15T10:30:00",
                    "end_time": "2025-01-15T10:35:00",
                    "duration_seconds": 300.5,
                    "uploaded_by": "john.doe",
                    "forecast_filename": "forecast_jan_2025.xlsx",
                    "allocation_success_rate": 0.95,
                    "error_type": null
                },
                ...
            ],
            "pagination": {
                "total": 150,
                "limit": 50,
                "offset": 0,
                "count": 50,
                "has_more": true
            }
        }

    Cache:
        TTL: 30 seconds (default)
        Key: allocation_executions:v1:{month}:{year}:{status}:{uploaded_by}:{limit}:{offset}
    """
    try:
        # Validate pagination
        limit, offset = validate_pagination(limit, offset, max_limit=100, default_limit=50)

        # Validate month/year if provided
        if month:
            from code.api.utils.validators import validate_month
            month = validate_month(month)
        if year:
            from code.api.utils.validators import validate_year
            year = validate_year(year)
        if status:
            from code.api.utils.validators import validate_execution_status
            status = validate_execution_status(status)

        # Generate cache key
        cache_key = generate_execution_list_cache_key(
            month=month,
            year=year,
            status=status,
            uploaded_by=uploaded_by,
            limit=limit,
            offset=offset
        )

        # Check cache first
        cached_response = allocation_list_cache.get(cache_key)
        if cached_response is not None:
            logger.debug(f"[Cache] Returning cached execution list for {cache_key}")
            return cached_response

        # Get executions from database
        records, total = list_executions(
            month=month,
            year=year,
            status=status,
            uploaded_by=uploaded_by,
            limit=limit,
            offset=offset
        )

        response = paginated_response(
            data=records,
            total=total,
            limit=limit,
            offset=offset
        )

        # Cache the response
        allocation_list_cache.set(cache_key, response)
        logger.info(f"[Cache] Cached execution list response: {len(records)} executions (total={total})")

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing allocation executions: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Failed to list executions", str(e))
        )


@router.get("/api/allocation/executions/{execution_id}")
def get_allocation_execution_details(execution_id: str):
    """
    Get detailed information about a specific allocation execution.

    Path Parameters:
        execution_id: UUID of the execution

    Returns:
        {
            "success": true,
            "data": {
                "execution_id": "uuid-string",
                "month": "January",
                "year": 2025,
                "status": "SUCCESS",
                "start_time": "2025-01-15T10:30:00",
                "end_time": "2025-01-15T10:35:00",
                "duration_seconds": 300.5,
                "forecast_filename": "forecast_jan_2025.xlsx",
                "roster_filename": "roster_dec_2024.xlsx",
                "roster_month_used": "December",
                "roster_year_used": 2024,
                "roster_was_fallback": false,
                "uploaded_by": "john.doe",
                "records_processed": 1250,
                "records_failed": 62,
                "allocation_success_rate": 0.95,
                "error_message": null,
                "error_type": null,
                "stack_trace": null,
                "config_snapshot": {...},
                "created_datetime": "2025-01-15T10:30:00"
            }
        }

    Raises:
        404: Execution not found

    Cache:
        TTL: Dynamic based on status
            - PENDING/IN_PROGRESS: 5 seconds (active monitoring)
            - SUCCESS/FAILED: 1 hour (immutable data)
        Key: allocation_execution_detail:v1:{execution_id}
    """
    # Generate cache key
    cache_key = generate_execution_detail_cache_key(execution_id)

    # Check cache first
    cached_response = allocation_detail_cache.get(cache_key)
    if cached_response is not None:
        logger.debug(f"[Cache] Returning cached execution detail for {execution_id}")
        return cached_response

    try:
        execution = get_execution_by_id(execution_id)

        if not execution:
            raise HTTPException(
                status_code=404,
                detail=error_response(f"Execution with ID {execution_id} not found")
            )

        response = success_response(data=execution)

        # Determine TTL based on execution status
        status = execution.get('status', '').upper()
        ttl_seconds = get_ttl_for_execution_status(status)

        # Cache the response with appropriate TTL
        allocation_detail_cache.set(cache_key, response, ttl=ttl_seconds)
        logger.info(f"[Cache] Cached execution detail (status={status}, ttl={ttl_seconds}s)")

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting allocation execution details: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Failed to get execution details", str(e))
        )
