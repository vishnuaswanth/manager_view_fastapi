"""
Utility functions for tracking history of forecast changes.

Provides functions to create, update, and retrieve history logs with complete
audit trail including field-level changes and summary statistics.
"""

import logging
import uuid
import json
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from sqlalchemy.exc import SQLAlchemyError
import pandas as pd

from code.logics.db import HistoryLogModel, HistoryChangeModel
from code.logics.config.change_types import validate_change_type
from code.api.dependencies import get_core_utils, get_logger

logger = get_logger(__name__)

# Get CoreUtils singleton instance (dependency injection pattern)
core_utils = get_core_utils()


def _validate_change_record(change: Dict, index: int) -> None:
    """
    Validate change dict has required structure before database insert.

    Args:
        change: Change dict to validate
        index: Index of change in list (for error messages)

    Raises:
        ValueError: If change record is missing required keys or has invalid structure
    """
    if not isinstance(change, dict):
        raise ValueError(f"Change at index {index} is not a dict")

    # Required keys for all changes
    required_keys = ['main_lob', 'state', 'case_type', 'case_id', 'field_name']
    missing = [k for k in required_keys if k not in change]
    if missing:
        raise ValueError(f"Change at index {index} missing required keys: {missing}")

    # Validate field_name is not empty
    if not change['field_name'] or not isinstance(change['field_name'], str):
        raise ValueError(f"Change at index {index} has invalid field_name: {change.get('field_name')}")

    # At least one of old_value or new_value should be present
    if 'old_value' not in change and 'new_value' not in change:
        raise ValueError(f"Change at index {index} missing both old_value and new_value")

    logger.debug(f"Change record at index {index} validated successfully")


def create_history_log(
    month: str,
    year: int,
    change_type: str,
    user: str,
    description: Optional[str],
    records_modified: int,
    summary_data: Optional[Dict]
) -> str:
    """
    Create a new history log entry.

    Args:
        month: Report month name (e.g., "April")
        year: Report year (e.g., 2025)
        change_type: Type of change (must be in CHANGE_TYPES)
        user: User identifier who made the change
        description: Optional user notes about the change
        records_modified: Count of modified records
        summary_data: Optional summary statistics dict (will be JSON serialized)

    Returns:
        history_log_id: UUID string for linking child records

    Raises:
        ValueError: If change_type is invalid
        SQLAlchemyError: If database operation fails
    """
    # Validate change type
    if not validate_change_type(change_type):
        raise ValueError(f"Invalid change type: {change_type}")

    # Generate UUID
    history_log_id = str(uuid.uuid4())

    try:
        db_manager = core_utils.get_db_manager(
            HistoryLogModel,
            limit=1,
            skip=0,
            select_columns=None
        )

        # Serialize summary data if provided
        summary_json = None
        if summary_data:
            summary_json = json.dumps(summary_data)

        # Create record
        history_record = {
            'history_log_id': history_log_id,
            'Month': month,
            'Year': year,
            'ChangeType': change_type,
            'Timestamp': datetime.now(),
            'User': user,
            'Description': description,
            'RecordsModified': records_modified,
            'SummaryData': summary_json,
            'CreatedBy': user,
            'CreatedDateTime': datetime.now()
        }

        df = pd.DataFrame([history_record])
        db_manager.save_to_db(df, replace=False)

        logger.info(f"Created history log: {history_log_id} for {month} {year}, type={change_type}")
        return history_log_id

    except Exception as e:
        logger.error(f"Failed to create history log: {e}", exc_info=True)
        raise


def add_history_changes(
    history_log_id: str,
    changes: List[Dict]
) -> None:
    """
    Add field-level changes to history log.

    Args:
        history_log_id: UUID linking to parent HistoryLogModel
        changes: List of change dicts, each containing:
            - main_lob: str
            - state: str
            - case_type: str
            - case_id: str
            - field_name: str (DOT notation, e.g., "Jun-25.fte_avail")
            - old_value: Any (will be converted to string)
            - new_value: Any (will be converted to string)
            - delta: float (optional)
            - month_label: str (optional, e.g., "Jun-25")

    Raises:
        SQLAlchemyError: If database operation fails
    """
    if not changes:
        logger.warning(f"No changes to add for history_log_id {history_log_id}")
        return

    # Validate all changes first before database operations
    try:
        for i, change in enumerate(changes):
            _validate_change_record(change, i)
    except ValueError as e:
        logger.error(f"Validation failed for changes: {e}", exc_info=True)
        raise

    try:
        db_manager = core_utils.get_db_manager(
            HistoryChangeModel,
            limit=len(changes),
            skip=0,
            select_columns=None
        )

        # Convert changes to DataFrame format
        change_records = []
        for change in changes:
            change_records.append({
                'history_log_id': history_log_id,
                'MainLOB': change['main_lob'],
                'State': change['state'],
                'CaseType': change['case_type'],
                'CaseID': change['case_id'],
                'FieldName': change['field_name'],
                'OldValue': str(change['old_value']) if change.get('old_value') is not None else None,
                'NewValue': str(change['new_value']) if change.get('new_value') is not None else None,
                'Delta': change.get('delta'),
                'MonthLabel': change.get('month_label'),
                'CreatedDateTime': datetime.now()
            })

        # Bulk insert
        df = pd.DataFrame(change_records)
        db_manager.save_to_db(df, replace=False)

        logger.info(f"Added {len(changes)} changes to history log {history_log_id}")

    except Exception as e:
        logger.error(f"Failed to add history changes: {e}", exc_info=True)
        raise


def create_complete_history_log(
    month: str,
    year: int,
    change_type: str,
    user: str,
    user_notes: Optional[str],
    modified_records: List[Dict],
    months_dict: Dict[str, str],
    summary_data: Dict
) -> str:
    """
    Create complete history log with changes in one operation.

    Combines create_history_log(), extract_specific_changes(), and add_history_changes()
    to eliminate code duplication in API routers.

    Args:
        month: Report month name
        year: Report year
        change_type: Type of change (from change_types config)
        user: User who made the change
        user_notes: Optional user description/notes
        modified_records: List of modified record dicts
        months_dict: Month index mapping (e.g., {"month1": "Jun-25"})
        summary_data: Pre-calculated summary data dict

    Returns:
        history_log_id: UUID of created history log

    Raises:
        ValueError: If validation fails or data is invalid
        SQLAlchemyError: If database operation fails

    Example:
        history_log_id = create_complete_history_log(
            month="March",
            year=2025,
            change_type=CHANGE_TYPE_BENCH_ALLOCATION,
            user="system",
            user_notes="Automated bench allocation",
            modified_records=modified_records_dict,
            months_dict=request.months,
            summary_data=summary_data
        )
    """
    from code.logics.bench_allocation_transformer import extract_specific_changes

    try:
        # Extract changes from modified records
        changes = extract_specific_changes(modified_records, months_dict)

        # Create history log
        history_log_id = create_history_log(
            month=month,
            year=year,
            change_type=change_type,
            user=user,
            description=user_notes,
            records_modified=len(modified_records),
            summary_data=summary_data
        )

        # Add field-level changes
        add_history_changes(history_log_id, changes)

        logger.info(
            f"Created complete history log: {history_log_id} with {len(changes)} changes"
        )

        return history_log_id

    except Exception as e:
        logger.error(f"Failed to create complete history log: {e}", exc_info=True)
        raise


def get_history_log_by_id(history_log_id: str) -> Optional[Dict]:
    """
    Get history log details by ID.

    Args:
        history_log_id: UUID of history log

    Returns:
        Dict with history log details or None if not found
    """
    try:
        db_manager = core_utils.get_db_manager(
            HistoryLogModel,
            limit=1,
            skip=0,
            select_columns=None
        )

        with db_manager.SessionLocal() as session:
            history_log = session.query(HistoryLogModel).filter(
                HistoryLogModel.history_log_id == history_log_id
            ).first()

            if not history_log:
                return None

            # Parse summary data if present
            summary_data = None
            if history_log.SummaryData:
                summary_data = json.loads(history_log.SummaryData)

            return {
                'id': history_log.history_log_id,
                'change_type': history_log.ChangeType,
                'month': history_log.Month,
                'year': history_log.Year,
                'timestamp': history_log.Timestamp.isoformat(),
                'user': history_log.User,
                'description': history_log.Description,
                'records_modified': history_log.RecordsModified,
                'summary_data': summary_data
            }

    except Exception as e:
        logger.error(f"Failed to get history log: {e}", exc_info=True)
        return None


def list_history_logs(
    month: Optional[str] = None,
    year: Optional[int] = None,
    change_types: Optional[List[str]] = None,
    page: int = 1,
    limit: int = 25
) -> Tuple[List[Dict], int]:
    """
    List history logs with filters and pagination.

    Args:
        month: Filter by month (optional)
        year: Filter by year (optional)
        change_types: Filter by change types list (optional, OR logic)
        page: Page number (1-indexed)
        limit: Records per page

    Returns:
        Tuple of (records list, total count)
    """
    try:
        offset = (page - 1) * limit

        db_manager = core_utils.get_db_manager(
            HistoryLogModel,
            limit=limit,
            skip=offset,
            select_columns=None
        )

        with db_manager.SessionLocal() as session:
            query = session.query(HistoryLogModel)

            # Apply filters (AND logic for month/year, OR logic for change_types)
            if month:
                query = query.filter(HistoryLogModel.Month == month)
            if year:
                query = query.filter(HistoryLogModel.Year == year)
            if change_types:
                # OR logic - match any of the specified change types
                query = query.filter(HistoryLogModel.ChangeType.in_(change_types))

            # Get total count
            total = query.count()

            # Order by most recent first
            query = query.order_by(HistoryLogModel.Timestamp.desc())

            # Pagination
            logs = query.offset(offset).limit(limit).all()

            # Format records
            records = []
            for log in logs:
                summary_data = None
                if log.SummaryData:
                    summary_data = json.loads(log.SummaryData)

                records.append({
                    'id': log.history_log_id,
                    'change_type': log.ChangeType,
                    'month': log.Month,
                    'year': log.Year,
                    'timestamp': log.Timestamp.isoformat(),
                    'user': log.User,
                    'description': log.Description,
                    'records_modified': log.RecordsModified,
                    'summary_data': summary_data
                })

            return records, total

    except Exception as e:
        logger.error(f"Failed to list history logs: {e}", exc_info=True)
        return [], 0


def get_history_log_with_changes(history_log_id: str) -> Optional[Dict]:
    """
    Get complete history log with all field-level changes.
    Used for Excel export generation.

    Args:
        history_log_id: UUID of history log

    Returns:
        Dict with:
            - history_log: parent record
            - changes: list of all field changes
        Returns None if history_log_id not found
    """
    try:
        # Get parent record
        history_log = get_history_log_by_id(history_log_id)
        if not history_log:
            return None

        # Get child records
        db_manager = core_utils.get_db_manager(
            HistoryChangeModel,
            limit=10000,  # High limit for complete export
            skip=0,
            select_columns=None
        )

        with db_manager.SessionLocal() as session:
            changes_query = session.query(HistoryChangeModel).filter(
                HistoryChangeModel.history_log_id == history_log_id
            ).order_by(
                HistoryChangeModel.MainLOB,
                HistoryChangeModel.State,
                HistoryChangeModel.CaseType,
                HistoryChangeModel.CaseID,
                HistoryChangeModel.MonthLabel,
                HistoryChangeModel.FieldName
            )

            changes = []
            for change in changes_query.all():
                changes.append({
                    'main_lob': change.MainLOB,
                    'state': change.State,
                    'case_type': change.CaseType,
                    'case_id': change.CaseID,
                    'field_name': change.FieldName,
                    'old_value': change.OldValue,
                    'new_value': change.NewValue,
                    'delta': change.Delta,
                    'month_label': change.MonthLabel
                })

            return {
                'history_log': history_log,
                'changes': changes
            }

    except Exception as e:
        logger.error(f"Failed to get history log with changes: {e}", exc_info=True)
        return None
