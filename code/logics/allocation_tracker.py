"""
Utility functions for tracking allocation process executions.

Provides functions to start, update, and complete execution tracking with complete
audit trail including source files, configuration snapshots, and error details.
"""

import logging
import uuid
import json
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from sqlalchemy.exc import SQLAlchemyError
import pandas as pd

from code.logics.db import AllocationExecutionModel
from code.settings import MODE, SQLITE_DATABASE_URL, MSSQL_DATABASE_URL
from code.logics.core_utils import CoreUtils

logger = logging.getLogger(__name__)

# Determine database URL based on mode
if MODE.upper() == "DEBUG":
    DATABASE_URL = SQLITE_DATABASE_URL
elif MODE.upper() == "PRODUCTION":
    DATABASE_URL = MSSQL_DATABASE_URL
else:
    raise ValueError("Invalid MODE specified in config.")

# Initialize CoreUtils instance (singleton for this module)
core_utils = CoreUtils(DATABASE_URL)


def start_execution(
    month: str,
    year: int,
    forecast_filename: str,
    roster_filename: str,
    roster_month_used: str,
    roster_year_used: int,
    roster_was_fallback: bool,
    uploaded_by: str
) -> str:
    """
    Start tracking a new allocation execution.

    Creates a new execution record with PENDING status and captures initial metadata
    including forecast file, roster file details, and fallback information.

    Args:
        month: Target month for allocation (e.g., "January")
        year: Target year for allocation (e.g., 2025)
        forecast_filename: Name of uploaded forecast file
        roster_filename: Name of roster file used (from database)
        roster_month_used: Actual month of roster data used
        roster_year_used: Actual year of roster data used
        roster_was_fallback: True if roster fallback to latest occurred
        uploaded_by: Username who uploaded the forecast file

    Returns:
        execution_id: UUID string for tracking this execution
    """
    execution_id = str(uuid.uuid4())

    try:
        db_manager = core_utils.get_db_manager(AllocationExecutionModel, limit=1, skip=0, select_columns=None)

        execution_record = {
            'execution_id': execution_id,
            'Month': month,
            'Year': year,
            'Status': 'PENDING',
            'StartTime': datetime.now(),
            'ForecastFilename': forecast_filename,
            'RosterFilename': roster_filename,
            'RosterMonthUsed': roster_month_used,
            'RosterYearUsed': roster_year_used,
            'RosterWasFallback': roster_was_fallback,
            'UploadedBy': uploaded_by
        }

        df = pd.DataFrame([execution_record])
        db_manager.save_to_db(df, replace=False)

        logger.info(f"Started execution tracking: {execution_id} for {month} {year}")
        return execution_id

    except Exception as e:
        logger.error(f"Failed to start execution tracking: {e}", exc_info=True)
        # Return ID anyway so execution can proceed
        return execution_id


def update_status(execution_id: str, status: str, config_snapshot: Optional[Dict] = None) -> None:
    """
    Update execution status (e.g., PENDING -> IN_PROGRESS).

    Args:
        execution_id: UUID of the execution
        status: New status ('PENDING', 'IN_PROGRESS', 'SUCCESS', 'FAILED', 'PARTIAL_SUCCESS')
        config_snapshot: Optional configuration snapshot to store (as JSON)
    """
    try:
        db_manager = core_utils.get_db_manager(AllocationExecutionModel, limit=1, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            execution = session.query(AllocationExecutionModel).filter(
                AllocationExecutionModel.execution_id == execution_id
            ).first()

            if execution:
                execution.Status = status
                if config_snapshot:
                    execution.ConfigSnapshot = json.dumps(config_snapshot)
                session.commit()
                logger.info(f"Updated execution {execution_id} status to {status}")
            else:
                logger.warning(f"Execution {execution_id} not found for status update")

    except Exception as e:
        logger.error(f"Failed to update execution status: {e}", exc_info=True)


def complete_execution(
    execution_id: str,
    success: bool,
    stats: Optional[Dict] = None,
    error: Optional[str] = None,
    error_type: Optional[str] = None,
    stack_trace: Optional[str] = None
) -> None:
    """
    Mark execution as complete with final status and statistics.

    Args:
        execution_id: UUID of the execution
        success: True if execution succeeded, False if failed
        stats: Optional statistics dict with keys:
            - records_processed: int
            - records_failed: int
            - allocation_success_rate: float
        error: Error message if failed
        error_type: Error type category if failed
        stack_trace: Full stack trace if failed
    """
    try:
        db_manager = core_utils.get_db_manager(AllocationExecutionModel, limit=1, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            execution = session.query(AllocationExecutionModel).filter(
                AllocationExecutionModel.execution_id == execution_id
            ).first()

            if execution:
                end_time = datetime.now()
                execution.EndTime = end_time
                execution.DurationSeconds = (end_time - execution.StartTime).total_seconds()

                if success:
                    execution.Status = 'SUCCESS'
                    if stats:
                        execution.RecordsProcessed = stats.get('records_processed')
                        execution.RecordsFailed = stats.get('records_failed', 0)
                        execution.AllocationSuccessRate = stats.get('allocation_success_rate')
                else:
                    execution.Status = 'FAILED'
                    execution.ErrorMessage = error
                    execution.ErrorType = error_type
                    execution.StackTrace = stack_trace

                session.commit()
                logger.info(f"Completed execution {execution_id} with status {execution.Status}")
            else:
                logger.warning(f"Execution {execution_id} not found for completion")

    except Exception as e:
        logger.error(f"Failed to complete execution tracking: {e}", exc_info=True)


def get_execution_by_id(execution_id: str) -> Optional[Dict]:
    """
    Get detailed execution information by ID.

    Args:
        execution_id: UUID of the execution

    Returns:
        Dictionary with complete execution details or None if not found
    """
    try:
        db_manager = core_utils.get_db_manager(AllocationExecutionModel, limit=1, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            execution = session.query(AllocationExecutionModel).filter(
                AllocationExecutionModel.execution_id == execution_id
            ).first()

            if not execution:
                return None

            return {
                'execution_id': execution.execution_id,
                'month': execution.Month,
                'year': execution.Year,
                'status': execution.Status,
                'start_time': execution.StartTime.isoformat() if execution.StartTime else None,
                'end_time': execution.EndTime.isoformat() if execution.EndTime else None,
                'duration_seconds': execution.DurationSeconds,
                'forecast_filename': execution.ForecastFilename,
                'roster_filename': execution.RosterFilename,
                'roster_month_used': execution.RosterMonthUsed,
                'roster_year_used': execution.RosterYearUsed,
                'roster_was_fallback': execution.RosterWasFallback,
                'uploaded_by': execution.UploadedBy,
                'records_processed': execution.RecordsProcessed,
                'records_failed': execution.RecordsFailed,
                'allocation_success_rate': execution.AllocationSuccessRate,
                'error_message': execution.ErrorMessage,
                'error_type': execution.ErrorType,
                'stack_trace': execution.StackTrace,
                'config_snapshot': json.loads(execution.ConfigSnapshot) if execution.ConfigSnapshot else None,
                'created_datetime': execution.CreatedDateTime.isoformat()
            }

    except Exception as e:
        logger.error(f"Failed to get execution: {e}", exc_info=True)
        return None


def list_executions(
    month: Optional[str] = None,
    year: Optional[int] = None,
    status: Optional[str] = None,
    uploaded_by: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> Tuple[List[Dict], int]:
    """
    List executions with filters. Returns minimal data for table view.

    Args:
        month: Filter by month (optional)
        year: Filter by year (optional)
        status: Filter by status (optional)
        uploaded_by: Filter by user (optional)
        limit: Maximum records to return (default: 50)
        offset: Pagination offset (default: 0)

    Returns:
        Tuple of (records list, total count)
        Records contain minimal data suitable for table display
    """
    try:
        db_manager = core_utils.get_db_manager(AllocationExecutionModel, limit=limit, skip=offset, select_columns=None)

        with db_manager.SessionLocal() as session:
            query = session.query(AllocationExecutionModel)

            # Apply filters
            if month:
                query = query.filter(AllocationExecutionModel.Month == month)
            if year:
                query = query.filter(AllocationExecutionModel.Year == year)
            if status:
                query = query.filter(AllocationExecutionModel.Status == status)
            if uploaded_by:
                query = query.filter(AllocationExecutionModel.UploadedBy == uploaded_by)

            # Get total count
            total = query.count()

            # Order by most recent first
            query = query.order_by(AllocationExecutionModel.StartTime.desc())

            # Pagination
            executions = query.offset(offset).limit(limit).all()

            # Return minimal data for table view
            records = []
            for exec in executions:
                records.append({
                    'execution_id': exec.execution_id,
                    'month': exec.Month,
                    'year': exec.Year,
                    'status': exec.Status,
                    'start_time': exec.StartTime.isoformat() if exec.StartTime else None,
                    'end_time': exec.EndTime.isoformat() if exec.EndTime else None,
                    'duration_seconds': exec.DurationSeconds,
                    'uploaded_by': exec.UploadedBy,
                    'forecast_filename': exec.ForecastFilename,
                    'allocation_success_rate': exec.AllocationSuccessRate,
                    'error_type': exec.ErrorType
                })

            return records, total

    except Exception as e:
        logger.error(f"Failed to list executions: {e}", exc_info=True)
        return [], 0
