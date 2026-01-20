"""
Edit View API Router.

Provides endpoints for bench allocation management, CPH updates, and history tracking
with preview/approval workflows.
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import Optional, List, Dict, TypeVar, Generic
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from code.logics.manager_view import get_available_report_months
from code.logics.bench_allocation import allocate_bench_for_month
from code.logics.bench_allocation_transformer import (
    transform_allocation_result_to_preview,
    calculate_summary_data,
    PreviewResponse
)
from code.logics.allocation_validity import validate_allocation_is_current
from code.logics.allocation_tracker import get_execution_by_id, mark_execution_bench_allocated
from code.logics.forecast_updater import update_forecast_from_modified_records
from code.logics.cph_update_transformer import (
    get_cph_data,
    calculate_cph_preview,
    update_forecast_from_cph_changes
)
from code.logics.config.change_types import (
    CHANGE_TYPE_BENCH_ALLOCATION,
    CHANGE_TYPE_CPH_UPDATE
)
from code.logics.core_utils import CoreUtils
from code.api.dependencies import get_core_utils, get_logger
from code.api.utils.update_handler import UpdateOperation, execute_update_operation

# Router setup
router = APIRouter()
logger = get_logger(__name__)

# Get CoreUtils singleton instance (dependency injection pattern)
core_utils = get_core_utils()


# ============ Pydantic Models ============

class MonthData(BaseModel):
    """Data for a single month in forecast modifications."""
    forecast: float = Field(ge=0, description="Client forecast value")
    fte_req: int = Field(ge=0, description="FTE Required")
    fte_avail: int = Field(ge=0, description="FTE Available")
    capacity: float = Field(ge=0, description="Capacity value")
    forecast_change: float = Field(default=0, description="Change in forecast")
    fte_req_change: int = Field(default=0, description="Change in FTE Required")
    fte_avail_change: int = Field(default=0, description="Change in FTE Available")
    capacity_change: float = Field(default=0, description="Change in capacity")

    class Config:
        extra = "forbid"  # Reject extra fields


class ModifiedForecastRecord(BaseModel):
    """Modified forecast record with month-specific data and changes."""
    case_id: str = Field(min_length=1, description="Case/Forecast ID")
    main_lob: str = Field(min_length=1, description="Main Line of Business")
    state: str = Field(min_length=2, max_length=3, description="State code (2-letter) or 'N/A'")
    case_type: str = Field(min_length=1, description="Case Type")
    target_cph: float = Field(gt=0, le=200, description="Target Cases Per Hour")
    target_cph_change: float = Field(default=0, description="Change in Target CPH")
    modified_fields: List[str] = Field(min_items=1, description="List of modified field paths")
    months: Dict[str, MonthData] = Field(
        description="Month-specific data keyed by month label (e.g., 'Jun-25')"
    )

    class Config:
        extra = "forbid"  # Strict validation

    def model_dump(self, **kwargs):
        """
        Flatten months for backward compatibility with forecast_updater.

        Transforms:
            {"months": {"Jun-25": {...}}}
        To:
            {"Jun-25": {...}}
        """
        data = super().model_dump(**kwargs)
        # Extract months and merge with top level
        months_data = data.pop('months', {})
        data.update(months_data)
        return data


class CPHRecord(BaseModel):
    """CPH record for update requests."""
    id: str = Field(min_length=1, description="CPH record ID")
    lob: str = Field(min_length=1, description="Line of Business")
    case_type: str = Field(min_length=1, description="Case Type")
    target_cph: float = Field(gt=0, le=200, description="Original Target CPH")
    modified_target_cph: float = Field(gt=0, le=200, description="Modified Target CPH")


# Define generic type variable for modified records
RecordType = TypeVar('RecordType')


class BasePreviewRequest(BaseModel, Generic[RecordType]):
    """Base class for preview requests with common fields."""
    month: str = Field(min_length=1, description="Report month name")
    year: int = Field(ge=2020, le=2050, description="Report year")
    modified_records: List[RecordType] = Field(
        min_items=1,
        description="List of records with modifications"
    )

    class Config:
        # Allow subclasses to be instantiated
        arbitrary_types_allowed = True


class BaseUpdateRequest(BaseModel, Generic[RecordType]):
    """
    Base class for update requests with common fields.

    Provides shared fields for bench allocation and CPH update operations:
    - month/year: Report period identification
    - months: Month index mapping for data structure
    - modified_records: Generic list of modified records (type specified by subclass)
    - user_notes: Optional description for history tracking
    """
    month: str = Field(min_length=1, description="Report month name")
    year: int = Field(ge=2020, le=2050, description="Report year")
    months: Dict[str, str] = Field(
        min_items=6,
        max_items=6,
        description="Month index mapping (e.g., {'month1': 'Jun-25'})"
    )
    modified_records: List[RecordType] = Field(
        min_items=1,
        description="List of modified records"
    )
    user_notes: Optional[str] = Field(None, max_length=1000, description="User notes/description")

    class Config:
        # Allow subclasses to be instantiated
        arbitrary_types_allowed = True


class BenchAllocationPreviewRequest(BaseModel):
    """Preview request for bench allocation operation."""
    month: str = Field(min_length=1, description="Report month name")
    year: int = Field(ge=2020, le=2050, description="Report year")


class BenchAllocationUpdateRequest(BaseUpdateRequest[ModifiedForecastRecord]):
    """
    Update request for bench allocation operation.

    Inherits common fields from BaseUpdateRequest and specifies
    ModifiedForecastRecord as the record type.
    """
    pass


class CPHPreviewRequest(BasePreviewRequest[CPHRecord]):
    """
    Preview request for CPH update operation.

    Inherits common fields from BasePreviewRequest and specifies
    CPHRecord as the record type.
    """
    pass


class CPHUpdateRequest(BaseUpdateRequest[ModifiedForecastRecord]):
    """
    Update request for CPH update operation.

    Uses ModifiedForecastRecord format (same as bench allocation)
    to accept the preview-calculated forecast changes.
    This ensures consistency across all forecast update operations.
    """
    pass


# ============ Bench Allocation Operation Configuration ============

def _validate_bench_allocation_request(request: BenchAllocationUpdateRequest) -> None:
    """
    Validate bench allocation specific requirements.

    Pydantic already handles most validation, but this allows for
    additional business logic validation if needed in the future.

    Args:
        request: Bench allocation update request

    Raises:
        HTTPException: If validation fails
    """
    # Additional validation can be added here as needed
    pass


def _perform_bench_allocation_update(
    request: BenchAllocationUpdateRequest,
    modified_records_dict: List[Dict],
    months_dict: Dict[str, str],
    core_utils: CoreUtils
) -> None:
    """
    Execute bench allocation forecast updates using unified updater.

    Args:
        request: Bench allocation update request
        modified_records_dict: Modified records as dict list
        months_dict: Month index mapping
        core_utils: CoreUtils instance

    Returns:
        None (void function)
    """
    update_forecast_from_modified_records(
        modified_records_dict,
        months_dict,
        request.month,
        request.year,
        core_utils,
        operation_type="bench_allocation"
    )


def _prepare_bench_allocation_history_records(
    request: BenchAllocationUpdateRequest,
    modified_records_dict: List[Dict],
    months_dict: Dict[str, str],
    core_utils: CoreUtils
) -> List[Dict]:
    """
    Prepare history records for bench allocation.

    Bench allocation uses modified records directly without transformation.

    Args:
        request: Bench allocation update request
        modified_records_dict: Modified records as dict list
        months_dict: Month index mapping
        core_utils: CoreUtils instance

    Returns:
        List of record dicts for history logging
    """
    return modified_records_dict


def _format_bench_allocation_response(
    update_result: None,
    history_log_id: str,
    request: BenchAllocationUpdateRequest
) -> Dict:
    """
    Format bench allocation success response.

    Args:
        update_result: Update operation result (None for bench allocation)
        history_log_id: UUID of created history log
        request: Bench allocation update request

    Returns:
        Response dict with success flag, message, counts, and history ID
    """
    return {
        "success": True,
        "message": "Bench allocation updated successfully",
        "records_updated": len(request.modified_records),
        "history_log_id": history_log_id
    }


# Create bench allocation operation configuration
bench_allocation_operation = UpdateOperation(
    change_type=CHANGE_TYPE_BENCH_ALLOCATION,
    perform_update=_perform_bench_allocation_update,
    prepare_history_records=_prepare_bench_allocation_history_records,
    format_response=_format_bench_allocation_response,
    validate_request=_validate_bench_allocation_request
)


# ============ CPH Update Operation Configuration ============

def _perform_cph_update(
    request: CPHUpdateRequest,
    modified_records_dict: List[Dict],
    months_dict: Dict[str, str],
    core_utils: CoreUtils
) -> tuple:
    """
    Execute CPH forecast updates using unified updater.

    Now uses the same ModifiedForecastRecord format and update logic
    as bench allocation for consistency.

    Args:
        request: CPH update request
        modified_records_dict: Modified forecast records as dict list (ModifiedForecastRecord format)
        months_dict: Month index mapping
        core_utils: CoreUtils instance

    Returns:
        Tuple of (records_updated, records_updated)

    Raises:
        HTTPException: If no CPH changes detected in request
    """
    # Use unified updater (same as bench allocation)
    update_forecast_from_modified_records(
        modified_records_dict,
        months_dict,
        request.month,
        request.year,
        core_utils,
        operation_type="cph_update"
    )

    # Count affected records
    records_updated = len(modified_records_dict)

    # Validate that changes were applied
    if records_updated == 0:
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": "No CPH changes detected in request"
            }
        )

    return (records_updated, records_updated)


def _prepare_cph_history_records(
    request: CPHUpdateRequest,
    modified_records_dict: List[Dict],
    months_dict: Dict[str, str],
    core_utils: CoreUtils
) -> List[Dict]:
    """
    Prepare history records for CPH updates.

    Now accepts ModifiedForecastRecord format directly from request.
    Preview data is already server-calculated and validated, so no
    recalculation is needed. This matches bench allocation behavior.

    Args:
        request: CPH update request
        modified_records_dict: Modified forecast records as dict list (ModifiedForecastRecord format)
        months_dict: Month index mapping
        core_utils: CoreUtils instance

    Returns:
        List of forecast record dicts for history logging
    """
    # Simply return the validated modified records
    # No recalculation needed - preview is server-generated and trusted
    return modified_records_dict


def _format_cph_response(
    update_result: tuple,
    history_log_id: str,
    request: CPHUpdateRequest
) -> Dict:
    """
    Format CPH update success response.

    Args:
        update_result: Tuple of (cph_records_updated, forecast_rows_affected)
        history_log_id: UUID of created history log
        request: CPH update request

    Returns:
        Response dict with success flag, message, counts, and history ID
    """
    cph_records_updated, forecast_rows_affected = update_result
    return {
        "success": True,
        "message": "CPH updated successfully",
        "cph_changes_applied": cph_records_updated,
        "forecast_rows_affected": forecast_rows_affected,
        "history_log_id": history_log_id
    }


# Create CPH update operation configuration. validation missing
cph_update_operation = UpdateOperation(
    change_type=CHANGE_TYPE_CPH_UPDATE,
    perform_update=_perform_cph_update,
    prepare_history_records=_prepare_cph_history_records,
    format_response=_format_cph_response
)


# ============ Endpoint 1: GET /api/allocation-reports ============

@router.get("/api/allocation-reports")
async def get_allocation_reports():
    """
    Get list of available allocation report months.

    Only returns months with valid allocations (is_valid=True in AllocationValidityModel).

    Returns:
        List of report months with metadata
    """
    try:
        reports = get_available_report_months(core_utils)
        return {
            "success": True,
            "data": reports,
            "total": len(reports)
        }
    except Exception as e:
        logger.error(f"Failed to get allocation reports: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": str(e)}
        )


# ============ Endpoint 2: POST /api/bench-allocation/preview ============

@router.post("/api/bench-allocation/preview")
async def preview_bench_allocation(request: BenchAllocationPreviewRequest):
    """
    Preview bench allocation changes before applying.

    Validates that bench allocation hasn't already been completed for this execution.

    Args:
        request: Month and year for allocation

    Returns:
        Preview response with modified records

    Raises:
        HTTPException: If allocation is invalid or bench allocation already completed
    """
    try:
        # STEP 1: Validate allocation is current
        validation_result = validate_allocation_is_current(
            request.month,
            request.year,
            core_utils
        )

        if not validation_result['valid']:
            raise HTTPException(
                status_code=400,
                detail={
                    "success": False,
                    "error": validation_result['error'],
                    "recommendation": validation_result.get('recommendation')
                }
            )

        execution_id = validation_result['execution_id']

        # STEP 2: Check if bench allocation already completed
        execution_details = get_execution_by_id(execution_id)

        if execution_details and execution_details.get('bench_allocation_completed'):
            completed_at = execution_details.get('bench_allocation_completed_at')
            raise HTTPException(
                status_code=400,
                detail={
                    "success": False,
                    "error": f"Bench allocation has already been completed for {request.month} {request.year}",
                    "completed_at": completed_at,
                    "execution_id": execution_id,
                    "recommendation": "To modify bench allocation, you must re-run the primary allocation first."
                }
            )

        # STEP 3: Proceed with allocation (existing logic)
        allocation_result = allocate_bench_for_month(
            request.month,
            request.year,
            core_utils
        )

        # Check if allocation succeeded
        if not allocation_result.success:
            error_detail = {
                "success": False,
                "error": allocation_result.error or "Bench allocation failed"
            }
            if allocation_result.recommendation:
                error_detail["recommendation"] = allocation_result.recommendation
            if allocation_result.context:
                error_detail["context"] = allocation_result.context
            raise HTTPException(status_code=400, detail=error_detail)

        # Check if any allocations were made
        if not allocation_result.allocations:
            # This is a success case with no action - return info message
            return {
                "success": True,
                "total_modified": 0,
                "modified_records": [],
                "info_message": allocation_result.info_message or "No bench capacity available for allocation"
            }

        # Transform to preview format
        preview_response = transform_allocation_result_to_preview(
            allocation_result,
            request.month,
            request.year,
            core_utils
        )

        return preview_response

    except HTTPException:
        raise
    except Exception as e:
        from code.logics.exceptions import EditViewException
        from sqlalchemy.exc import SQLAlchemyError

        # Custom domain exceptions - already have structured error info
        if isinstance(e, EditViewException):
            logger.warning(f"Bench allocation error: {e.message}", exc_info=True)
            raise HTTPException(
                status_code=e.http_status,
                detail=e.to_dict()
            )

        # Database errors
        if isinstance(e, SQLAlchemyError):
            logger.error(f"Database error during bench allocation: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={
                    "success": False,
                    "error": "Database operation failed",
                    "recommendation": "Contact system administrator if this persists."
                }
            )

        # Unexpected errors
        logger.error(f"Unexpected error during bench allocation: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "recommendation": "Contact system administrator."
            }
        )


# ============ Endpoint 3: POST /api/bench-allocation/update ============

@router.post("/api/bench-allocation/update")
async def update_bench_allocation(request: BenchAllocationUpdateRequest):
    """
    Apply bench allocation changes to forecast data.

    Uses generic update handler with bench allocation configuration.
    After successful update, marks the execution as bench allocated to prevent duplicate operations.

    Args:
        request: Bench allocation update request with modified records

    Returns:
        Success response with records updated count

    Raises:
        HTTPException: If update fails or validation errors occur
    """
    try:
        # Execute the update operation
        response = execute_update_operation(request, bench_allocation_operation, core_utils)

        # After successful update, mark execution as bench allocated
        try:
            # Get the current valid execution_id for this month/year
            validation_result = validate_allocation_is_current(
                request.month,
                request.year,
                core_utils
            )

            if validation_result['valid']:
                execution_id = validation_result['execution_id']
                mark_execution_bench_allocated(execution_id, core_utils)
                logger.info(f"Marked execution {execution_id} as bench allocated after successful update")
            else:
                logger.warning(f"Could not mark execution as bench allocated: {validation_result.get('error')}")

        except Exception as e:
            # Log error but don't fail the request - update was already successful
            logger.error(f"Failed to mark execution as bench allocated: {e}", exc_info=True)

        return response

    except HTTPException:
        raise
    except Exception as e:
        from code.logics.exceptions import EditViewException
        from sqlalchemy.exc import SQLAlchemyError

        # Custom domain exceptions - already have structured error info
        if isinstance(e, EditViewException):
            logger.warning(f"Bench allocation update error: {e.message}", exc_info=True)
            raise HTTPException(
                status_code=e.http_status,
                detail=e.to_dict()
            )

        # Database errors
        if isinstance(e, SQLAlchemyError):
            logger.error(f"Database error during bench allocation update: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={
                    "success": False,
                    "error": "Database operation failed during update",
                    "recommendation": "Contact system administrator if this persists."
                }
            )

        # Unexpected errors
        logger.error(f"Unexpected error during bench allocation update: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "recommendation": "Contact system administrator."
            }
        )


# ============ Endpoint 4: GET /api/edit-view/target-cph/data/ ============

@router.get("/api/edit-view/target-cph/data/")
async def get_target_cph_data(
    month: str = Query(...),
    year: int = Query(...)
):
    """
    Get unique Target CPH values by LOB/CaseType.

    Args:
        month: Report month name
        year: Report year

    Returns:
        List of CPH data records
    """
    try:
        cph_data = get_cph_data(month, year, core_utils)

        return {
            "success": True,
            "data": cph_data,
            "total": len(cph_data)
        }

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": str(e)}
        )
    except Exception as e:
        logger.error(f"Failed to get CPH data: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": str(e)}
        )


# ============ Endpoint 5: POST /api/edit-view/target-cph/preview/ ============

@router.post("/api/edit-view/target-cph/preview/", response_model=PreviewResponse)
async def preview_target_cph_changes(request: CPHPreviewRequest) -> PreviewResponse:
    """
    Preview forecast impact of CPH changes.

    Args:
        request: CPH preview request with modified records

    Returns:
        PreviewResponse: Validated Pydantic model with affected forecast records
    """
    try:
        # Validate request
        if not request.modified_records:
            raise HTTPException(
                status_code=400,
                detail={"success": False, "error": "modified_records cannot be empty"}
            )

        # Convert Pydantic models to dicts for transformer functions
        modified_records_dict = [record.model_dump() for record in request.modified_records]

        # Calculate preview
        preview_response = calculate_cph_preview(
            request.month,
            request.year,
            modified_records_dict,
            core_utils
        )

        return preview_response

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": str(e)}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to preview CPH changes: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": str(e)}
        )


# ============ Endpoint 6: POST /api/edit-view/target-cph/update/ ============

@router.post("/api/edit-view/target-cph/update/")
async def update_target_cph(request: CPHUpdateRequest):
    """
    Apply CPH changes to forecast data.

    Uses generic update handler with CPH update configuration.

    Args:
        request: CPH update request with modified records

    Returns:
        Success response with update counts
    """
    return execute_update_operation(request, cph_update_operation, core_utils)
