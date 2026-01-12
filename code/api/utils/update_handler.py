"""
Generic update operation handler for Edit View endpoints.

Eliminates code duplication between bench allocation, CPH updates, and future update types
by using the Strategy Pattern with operation-specific callbacks.
"""

from typing import Callable, Dict, Any, List, Optional
from pydantic import BaseModel
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from code.logics.core_utils import CoreUtils
from code.logics.bench_allocation_transformer import calculate_summary_data
from code.logics.history_logger import create_complete_history_log
from code.api.dependencies import get_logger

logger = get_logger(__name__)


class UpdateOperation:
    """
    Configuration for a specific update operation using Strategy Pattern.

    Each update operation (bench allocation, CPH update, etc.) provides callbacks
    for operation-specific logic while sharing common workflow implementation.

    Attributes:
        change_type: History log change type constant (e.g., CHANGE_TYPE_BENCH_ALLOCATION)
        perform_update: Callback to execute the database update operation
        prepare_history_records: Callback to prepare records for history logging
        format_response: Callback to format the final API response
        validate_request: Optional callback for operation-specific validation
    """

    def __init__(
        self,
        change_type: str,
        perform_update: Callable[[BaseModel, List[Dict], Dict[str, str], CoreUtils], Any],
        prepare_history_records: Callable[[BaseModel, List[Dict], Dict[str, str], CoreUtils], List[Dict]],
        format_response: Callable[[Any, str, BaseModel], Dict],
        validate_request: Optional[Callable[[BaseModel], None]] = None,
    ):
        """
        Initialize update operation configuration.

        Args:
            change_type: History log change type identifier
            perform_update: Function(request, modified_records_dict, months_dict, core_utils) -> Any
                Executes the database update operation.
                Returns operation-specific result (void, tuple, etc.)
            prepare_history_records: Function(request, modified_records_dict, months_dict, core_utils) -> List[Dict]
                Prepares records to be logged in history (may transform/recalculate).
                Returns list of record dicts for history logging.
            format_response: Function(update_result, history_log_id, request) -> Dict
                Formats the final API response dict.
                Returns dict with success, message, and operation-specific fields.
            validate_request: Optional Function(request) -> None
                Performs operation-specific validation.
                Raises HTTPException on validation failure.
        """
        self.change_type = change_type
        self.perform_update = perform_update
        self.prepare_history_records = prepare_history_records
        self.format_response = format_response
        self.validate_request = validate_request


def execute_update_operation(
    request: BaseModel,
    operation: UpdateOperation,
    core_utils: CoreUtils
) -> Dict:
    """
    Execute generic update operation with transaction management and history logging.

    This function implements the common workflow for all update operations:
    1. Validate request (common + operation-specific)
    2. Start database transaction
    3. Convert Pydantic models to dicts
    4. Perform update (operation-specific)
    5. Prepare history records (operation-specific)
    6. Calculate summary data
    7. Create history log
    8. Commit transaction (automatic via context manager)
    9. Format response (operation-specific)

    Args:
        request: Pydantic request model with fields:
            - month: str (report month name)
            - year: int (report year)
            - months: Dict[str, str] (month index mapping)
            - modified_records: List (modified records)
            - user_notes: Optional[str] (user notes)
        operation: UpdateOperation configuration with callbacks
        core_utils: CoreUtils instance for database access

    Returns:
        Operation-specific response dict (via operation.format_response)

    Raises:
        HTTPException:
            - 400 if validation fails
            - 500 if database operation fails

    Example:
        ```python
        # Define operation configuration
        my_operation = UpdateOperation(
            change_type=CHANGE_TYPE_CUSTOM,
            perform_update=my_update_function,
            prepare_history_records=my_history_prep,
            format_response=my_response_formatter
        )

        # Execute update
        result = execute_update_operation(request, my_operation, core_utils)
        ```
    """
    try:
        # Step 1: Custom validation (operation-specific)
        if operation.validate_request:
            operation.validate_request(request)

        # Step 2: Common validation
        if not hasattr(request, 'modified_records') or not request.modified_records:
            raise HTTPException(
                status_code=400,
                detail={"success": False, "error": "modified_records cannot be empty"}
            )

        if not hasattr(request, 'months') or not request.months:
            raise HTTPException(
                status_code=400,
                detail={"success": False, "error": "months dict is required"}
            )

        # Step 3: Start database transaction
        db_manager = core_utils.get_db_manager(
            None,  # Not specific to a model
            limit=1,
            skip=0,
            select_columns=None
        )

        with db_manager.SessionLocal() as session:
            try:
                # Step 4: Convert Pydantic models to dicts
                modified_records_dict = [
                    record.model_dump() for record in request.modified_records
                ]

                # Step 5: Perform update (operation-specific)
                logger.info(
                    f"Executing {operation.change_type} update for {request.month} {request.year}"
                )
                update_result = operation.perform_update(
                    request,
                    modified_records_dict,
                    request.months,
                    core_utils
                )

                # Step 6: Prepare history records (operation-specific)
                # Some operations use records directly, others recalculate/transform
                history_records = operation.prepare_history_records(
                    request,
                    modified_records_dict,
                    request.months,
                    core_utils
                )

                # Step 7: Calculate summary data
                summary_data = calculate_summary_data(
                    history_records,
                    request.months,
                    request.month,
                    request.year
                )

                # Step 8: Create history log
                history_log_id = create_complete_history_log(
                    month=request.month,
                    year=request.year,
                    change_type=operation.change_type,
                    user="system",  # TODO: Extract from JWT token when auth is implemented
                    user_notes=request.user_notes if hasattr(request, 'user_notes') else None,
                    modified_records=history_records,
                    months_dict=request.months,
                    summary_data=summary_data
                )

                logger.info(
                    f"Update operation completed: {operation.change_type}, "
                    f"history_log_id={history_log_id}"
                )

                # Step 9: Format response (operation-specific)
                return operation.format_response(update_result, history_log_id, request)

            except (ValueError, KeyError, AttributeError) as e:
                # Data validation or structure errors → 400 Bad Request
                logger.error(
                    f"Data validation error in {operation.change_type}: {e}",
                    exc_info=True
                )
                raise HTTPException(
                    status_code=400,
                    detail={"success": False, "error": f"Invalid data: {str(e)}"}
                )
            except SQLAlchemyError as e:
                # Database errors → 500 Internal Server Error
                # Context manager will handle rollback automatically
                logger.error(
                    f"Database transaction failed for {operation.change_type}: {e}",
                    exc_info=True
                )
                raise HTTPException(
                    status_code=500,
                    detail={"success": False, "error": "Database operation failed"}
                )
            except HTTPException:
                # Re-raise HTTPExceptions from operation callbacks
                raise
            except Exception as e:
                # Unexpected errors
                logger.critical(
                    f"Unexpected error in {operation.change_type} update: {e}",
                    exc_info=True
                )
                raise

    except HTTPException:
        raise
    except Exception as e:
        logger.critical(f"Failed to execute update operation: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": str(e)}
        )
