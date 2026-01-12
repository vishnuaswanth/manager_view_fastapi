"""
History Log API Router.

Provides endpoints for viewing and downloading history logs of forecast modifications,
including bench allocation and CPH updates.
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import Optional, List
from code.logics.history_logger import (
    list_history_logs,
    get_history_log_with_changes
)
from code.logics.history_excel_generator import generate_history_excel
from code.logics.config.change_types import validate_change_type
from code.api.dependencies import get_logger

# Router setup
router = APIRouter()
logger = get_logger(__name__)


# ============ Endpoint 1: GET /api/history-log ============

@router.get("/api/history-log")
async def get_history_log(
    month: Optional[str] = None,
    year: Optional[int] = None,
    change_types: Optional[List[str]] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100)
):
    """
    List history logs with filters and pagination.

    Args:
        month: Filter by month (optional)
        year: Filter by year (optional)
        change_types: Filter by change types (optional, OR logic)
        page: Page number (1-indexed)
        limit: Records per page (1-100)

    Returns:
        Paginated history log list with structure:
        {
            "success": True,
            "data": [
                {
                    "history_log_id": "uuid",
                    "month": "April",
                    "year": 2025,
                    "change_type": "Bench Allocation",
                    "user": "system",
                    "created_at": "2025-01-12T10:30:00",
                    "records_modified": 15,
                    "summary_data": {...}
                },
                ...
            ],
            "total": 100,
            "page": 1,
            "limit": 25,
            "has_more": True
        }

    Raises:
        HTTPException: 400 if invalid change_type provided, 500 on server error
    """
    try:
        # Validate change_types if provided
        if change_types:
            for change_type in change_types:
                if not validate_change_type(change_type):
                    raise HTTPException(
                        status_code=400,
                        detail={"success": False, "error": f"Invalid change type: {change_type}"}
                    )

        # List history logs
        records, total = list_history_logs(
            month=month,
            year=year,
            change_types=change_types,
            page=page,
            limit=limit
        )

        return {
            "success": True,
            "data": records,
            "total": total,
            "page": page,
            "limit": limit,
            "has_more": (page * limit) < total
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list history logs: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": str(e)}
        )


# ============ Endpoint 2: GET /api/history-log/{history_log_id}/download ============

@router.get("/api/history-log/{history_log_id}/download")
async def download_history_excel(history_log_id: str):
    """
    Download history log as Excel file.

    Generates an Excel workbook containing:
    - Summary sheet with change metadata
    - Changes sheet with field-level modifications

    Args:
        history_log_id: UUID of history log

    Returns:
        StreamingResponse: Excel file download with proper headers

    Raises:
        HTTPException: 404 if history log not found, 500 on server error
    """
    try:
        # Get history log with changes
        history_data = get_history_log_with_changes(history_log_id)

        if not history_data:
            raise HTTPException(
                status_code=404,
                detail={"success": False, "error": "History log entry not found"}
            )

        # Generate Excel file
        excel_buffer = generate_history_excel(
            history_log_data=history_data,
            changes=history_data.get('changes', [])
        )

        # Create filename
        month = history_data['month']
        year = history_data['year']
        change_type = history_data['change_type'].replace(' ', '_')
        filename = f"history_log_{change_type}_{month}_{year}_{history_log_id[:8]}.xlsx"

        # Return as streaming response
        return StreamingResponse(
            excel_buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download history Excel: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": str(e)}
        )
