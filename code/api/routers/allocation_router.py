"""
Allocation report download and execution tracking endpoints.

Provides endpoints for:
- Downloading allocation reports by execution_id (recommended)
- Downloading allocation reports by month/year (backward compatibility - fetches latest execution)
- Listing allocation execution history
- Getting detailed execution information

Report Types:
- bucket_summary: Bucket structure and vendor details
- bucket_after_allocation: Allocation status per bucket
- roster_allotment: Vendor-level allocation details

API Endpoints:
  By execution_id (recommended):
    GET /api/allocation/executions/{execution_id}/reports/bucket_summary
    GET /api/allocation/executions/{execution_id}/reports/bucket_after_allocation
    GET /api/allocation/executions/{execution_id}/reports/roster_allotment

  By month/year (backward compatible):
    GET /download_allocation_report/bucket_summary?month={month}&year={year}
    GET /download_allocation_report/bucket_after_allocation?month={month}&year={year}
    GET /download_allocation_report/roster_allotment?month={month}&year={year}
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
import pandas as pd
import io
import logging
from typing import Optional, List

from code.logics.db import DBManager, AllocationReportsModel
from code.logics.allocation_tracker import list_executions, get_execution_by_id, get_execution_kpis
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

        # Retrieve latest execution's report data for backward compatibility
        df = db_manager.get_latest_execution_report(month, year, 'bucket_summary')

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

        # Retrieve latest execution's report data for backward compatibility
        df = db_manager.get_latest_execution_report(month, year, 'bucket_after_allocation')

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

        # Retrieve latest execution's report data for backward compatibility
        df = db_manager.get_latest_execution_report(month, year, 'roster_allotment')

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


@router.get("/api/allocation/executions/{execution_id}/reports/bucket_summary")
def download_allocation_bucket_summary_by_execution(execution_id: str):
    """
    Download bucket summary allocation report by execution_id as Excel file.

    Path Parameters:
        execution_id: UUID of the execution

    Returns:
        Excel file with bucket summary data (Summary and Details sheets)

    Response Headers:
        Content-Disposition: attachment; filename=bucket_summary_{execution_id}.xlsx

    Raises:
        404: Report not found for execution_id
    """
    try:
        # Initialize DBManager
        db_manager = DBManager(
            database_url=DATABASE_URL,
            Model=AllocationReportsModel,
            limit=1000,
            skip=0,
            select_columns=None
        )

        # Retrieve report data by execution_id
        df = db_manager.get_allocation_report_by_execution_id_as_dataframe(execution_id, 'bucket_summary')

        if df is None or df.empty:
            raise HTTPException(
                status_code=404,
                detail=error_response(f"No bucket_summary report found for execution {execution_id}")
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

        filename = f"bucket_summary_{execution_id}.xlsx"

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading bucket_summary report by execution_id: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Failed to download report", str(e))
        )


@router.get("/api/allocation/executions/{execution_id}/reports/bucket_after_allocation")
def download_allocation_bucket_after_allocation_by_execution(execution_id: str):
    """
    Download buckets after allocation report by execution_id as Excel file.

    Path Parameters:
        execution_id: UUID of the execution

    Returns:
        Excel file with allocation status per bucket

    Response Headers:
        Content-Disposition: attachment; filename=buckets_after_allocation_{execution_id}.xlsx

    Raises:
        404: Report not found for execution_id
    """
    try:
        # Initialize DBManager
        db_manager = DBManager(
            database_url=DATABASE_URL,
            Model=AllocationReportsModel,
            limit=1000,
            skip=0,
            select_columns=None
        )

        # Retrieve report data by execution_id
        df = db_manager.get_allocation_report_by_execution_id_as_dataframe(execution_id, 'bucket_after_allocation')

        if df is None or df.empty:
            raise HTTPException(
                status_code=404,
                detail=error_response(f"No bucket_after_allocation report found for execution {execution_id}")
            )

        # Create Excel file
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)

        filename = f"buckets_after_allocation_{execution_id}.xlsx"

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading bucket_after_allocation report by execution_id: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Failed to download report", str(e))
        )


@router.get("/api/allocation/executions/{execution_id}/reports/roster_allotment")
def download_allocation_roster_allotment_by_execution(execution_id: str):
    """
    Download roster allotment allocation report by execution_id as Excel file.

    Path Parameters:
        execution_id: UUID of the execution

    Returns:
        Excel file with vendor-level allocation details

    Response Headers:
        Content-Disposition: attachment; filename=roster_allotment_{execution_id}.xlsx

    Raises:
        404: Report not found for execution_id
    """
    try:
        # Initialize DBManager
        db_manager = DBManager(
            database_url=DATABASE_URL,
            Model=AllocationReportsModel,
            limit=1000,
            skip=0,
            select_columns=None
        )

        # Retrieve report data by execution_id
        df = db_manager.get_allocation_report_by_execution_id_as_dataframe(execution_id, 'roster_allotment')

        if df is None or df.empty:
            raise HTTPException(
                status_code=404,
                detail=error_response(f"No roster_allotment report found for execution {execution_id}")
            )

        # Create Excel file
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)

        filename = f"roster_allotment_{execution_id}.xlsx"

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading roster_allotment report by execution_id: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Failed to download report", str(e))
        )


@router.get("/api/allocation/executions")
def list_allocation_executions(
    month: Optional[str] = None,
    year: Optional[int] = None,
    status: Optional[List[str]] = Query(None),
    uploaded_by: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """
    List allocation executions with minimal data for table view.

    Query Parameters:
        month: Filter by month (optional)
        year: Filter by year (optional)
        status: Filter by status (can specify multiple times, e.g., ?status=SUCCESS&status=FAILED) (optional)
                Valid values: PENDING, IN_PROGRESS, SUCCESS, FAILED, PARTIAL_SUCCESS
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

    Examples:
        # Single status filter
        GET /api/allocation/executions?month=January&year=2025&status=SUCCESS

        # Multiple status filter
        GET /api/allocation/executions?status=SUCCESS&status=FAILED

        # Filter active executions
        GET /api/allocation/executions?status=PENDING&status=IN_PROGRESS

    Cache:
        TTL: 30 seconds (default)
        Key: allocation_executions:v1:{month}:{year}:{status}:{uploaded_by}:{limit}:{offset}
        Note: For multiple statuses, key uses comma-separated sorted values
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

        # Validate status list if provided
        validated_statuses = None
        if status:
            from code.api.utils.validators import validate_execution_status
            validated_statuses = [validate_execution_status(s) for s in status]

        # Generate cache key (convert list to sorted tuple for consistent hashing)
        cache_key = generate_execution_list_cache_key(
            month=month,
            year=year,
            status=tuple(sorted(validated_statuses)) if validated_statuses else None,
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
            status=validated_statuses,
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


@router.get("/api/allocation/executions/kpi")
def get_allocation_execution_kpis(
    month: Optional[str] = None,
    year: Optional[int] = None,
    status: Optional[List[str]] = Query(None),
    uploaded_by: Optional[str] = None
):
    """
    Get aggregated KPI metrics for allocation executions.

    Supports flexible filtering - any combination of filters can be applied:
    - Just year (e.g., all 2025 executions)
    - Month and year (e.g., January 2025)
    - Just status(es) (e.g., all failed executions)
    - Just uploaded_by (e.g., all executions by user)
    - Any combination of the above

    Query Parameters:
        month: Filter by month (optional)
        year: Filter by year (optional)
        status: Filter by status (can specify multiple times) (optional)
                Valid values: PENDING, IN_PROGRESS, SUCCESS, FAILED, PARTIAL_SUCCESS
        uploaded_by: Filter by username (optional)

    Returns:
        {
            "success": true,
            "data": {
                "total_executions": 150,
                "success_rate": 0.85,
                "average_duration_seconds": 320.5,
                "failed_count": 12,
                "partial_success_count": 8,
                "in_progress_count": 2,
                "pending_count": 3,
                "success_count": 125,
                "total_records_processed": 187500,
                "total_records_failed": 9375
            },
            "timestamp": "2025-01-15T14:30:00Z"
        }

    Examples:
        # All KPIs (no filters)
        GET /api/allocation/executions/kpi

        # KPIs for specific year
        GET /api/allocation/executions/kpi?year=2025

        # KPIs for specific month/year
        GET /api/allocation/executions/kpi?month=January&year=2025

        # KPIs for specific user
        GET /api/allocation/executions/kpi?uploaded_by=john.doe

        # KPIs for specific statuses
        GET /api/allocation/executions/kpi?status=SUCCESS&status=FAILED

        # Combined filters
        GET /api/allocation/executions/kpi?year=2025&status=SUCCESS&uploaded_by=john.doe

    Cache:
        TTL: 60 seconds
        Key: allocation_executions_kpi:v1:{month}:{year}:{status}:{uploaded_by}
    """
    try:
        # Validate month/year if provided
        if month:
            from code.api.utils.validators import validate_month
            month = validate_month(month)
        if year:
            from code.api.utils.validators import validate_year
            year = validate_year(year)

        # Validate status list if provided
        validated_statuses = None
        if status:
            from code.api.utils.validators import validate_execution_status
            validated_statuses = [validate_execution_status(s) for s in status]

        # Generate cache key
        from datetime import datetime, timezone
        status_part = tuple(sorted(validated_statuses)) if validated_statuses else None
        cache_key = f"allocation_executions_kpi:v1:{month or ''}:{year or ''}:{status_part or ''}:{uploaded_by or ''}"

        # Check cache first
        cached_response = allocation_list_cache.get(cache_key)
        if cached_response is not None:
            logger.debug(f"[Cache] Returning cached KPI data for {cache_key}")
            return cached_response

        # Get KPI data
        kpi_data = get_execution_kpis(
            month=month,
            year=year,
            status=validated_statuses,
            uploaded_by=uploaded_by
        )

        if kpi_data is None:
            raise HTTPException(
                status_code=500,
                detail=error_response("Failed to calculate KPIs")
            )

        response = {
            "success": True,
            "data": kpi_data,
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        }

        # Cache the response (60 seconds TTL)
        allocation_list_cache.set(cache_key, response, ttl=60)
        logger.info(f"[Cache] Cached KPI response (60s TTL)")

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting allocation execution KPIs: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_response("Failed to get execution KPIs", str(e))
        )
