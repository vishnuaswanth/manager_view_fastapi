"""
Allocation Validity Tracking Module

This module provides utilities for tracking and managing allocation validity.
When allocations are performed, a validity record is created. If forecast data
is manually edited through any API, the allocation is invalidated to prevent
using stale allocation reports for bench allocation.
"""

from typing import Dict, Optional
from datetime import datetime
import logging

from code.logics.db import AllocationValidityModel
from code.logics.core_utils import CoreUtils

logger = logging.getLogger(__name__)


def create_validity_record(
    month: str,
    year: int,
    execution_id: str,
    core_utils: CoreUtils
) -> Dict:
    """
    Create or update validity record when allocation completes successfully.

    Args:
        month: Month name (e.g., "January")
        year: Year (e.g., 2025)
        execution_id: UUID of the allocation execution
        core_utils: CoreUtils instance for database access

    Returns:
        Dict with success status and message
    """
    try:
        db_manager = core_utils.get_db_manager(AllocationValidityModel, limit=1, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            # Check if record exists (UPSERT)
            existing = session.query(AllocationValidityModel).filter(
                AllocationValidityModel.month == month,
                AllocationValidityModel.year == year
            ).first()

            if existing:
                # Update existing record
                existing.allocation_execution_id = execution_id
                existing.is_valid = True
                existing.created_datetime = datetime.now()
                existing.invalidated_datetime = None
                existing.invalidated_reason = None
                logger.info(f"Updated allocation validity for {month} {year} (execution: {execution_id})")
            else:
                # Create new record
                validity_record = AllocationValidityModel(
                    month=month,
                    year=year,
                    allocation_execution_id=execution_id,
                    is_valid=True,
                    created_datetime=datetime.now()
                )
                session.add(validity_record)
                logger.info(f"Created allocation validity for {month} {year} (execution: {execution_id})")

            session.commit()

            return {
                'success': True,
                'message': f'Allocation marked as valid for {month} {year}'
            }

    except Exception as e:
        logger.error(f"Error creating validity record: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def invalidate_allocation(
    month: str,
    year: int,
    reason: str,
    core_utils: CoreUtils
) -> Dict:
    """
    Invalidate allocation when forecast data is manually edited.

    This should be called from ALL APIs that modify ForecastModel data:
    - Forecast upload
    - Manual FTE edits
    - Capacity adjustments
    - Bulk updates

    Args:
        month: Month name (e.g., "January")
        year: Year (e.g., 2025)
        reason: Reason for invalidation (e.g., "Manual edit via API")
        core_utils: CoreUtils instance for database access

    Returns:
        Dict with success status and message
    """
    try:
        db_manager = core_utils.get_db_manager(AllocationValidityModel, limit=1, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            validity_record = session.query(AllocationValidityModel).filter(
                AllocationValidityModel.month == month,
                AllocationValidityModel.year == year
            ).first()

            if validity_record:
                if validity_record.is_valid:
                    # Mark as invalid
                    validity_record.is_valid = False
                    validity_record.invalidated_datetime = datetime.now()
                    validity_record.invalidated_reason = reason
                    session.commit()

                    logger.warning(f"Invalidated allocation for {month} {year}: {reason}")

                    return {
                        'success': True,
                        'message': f'Allocation invalidated for {month} {year}',
                        'was_valid': True
                    }
                else:
                    logger.info(f"Allocation for {month} {year} was already invalid")
                    return {
                        'success': True,
                        'message': f'Allocation already invalid for {month} {year}',
                        'was_valid': False
                    }
            else:
                logger.info(f"No allocation validity record found for {month} {year}")
                return {
                    'success': True,
                    'message': f'No allocation record for {month} {year}',
                    'was_valid': None
                }

    except Exception as e:
        logger.error(f"Error invalidating allocation: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def validate_allocation_is_current(
    month: str,
    year: int,
    core_utils: CoreUtils
) -> Dict:
    """
    Check if allocation is still valid for month/year.

    This should be called BEFORE running bench allocation to ensure
    the allocation reports are not stale.

    Args:
        month: Month name (e.g., "January")
        year: Year (e.g., 2025)
        core_utils: CoreUtils instance for database access

    Returns:
        Dict with validation result:
        - valid: bool - Whether allocation is valid
        - execution_id: str - Execution ID if valid
        - error: str - Error message if not valid
        - reason: str - Invalidation reason if applicable
        - invalidated_at: datetime - When invalidated
        - recommendation: str - What to do next
    """
    try:
        db_manager = core_utils.get_db_manager(AllocationValidityModel, limit=1, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            validity_record = session.query(AllocationValidityModel).filter(
                AllocationValidityModel.month == month,
                AllocationValidityModel.year == year
            ).first()

            if not validity_record:
                return {
                    'valid': False,
                    'error': f'No allocation found for {month} {year}. Run initial allocation first.',
                    'recommendation': 'Upload forecast and run initial allocation process.'
                }

            if not validity_record.is_valid:
                return {
                    'valid': False,
                    'error': f'Allocation for {month} {year} was invalidated.',
                    'reason': validity_record.invalidated_reason or 'Unknown reason',
                    'invalidated_at': validity_record.invalidated_datetime,
                    'recommendation': 'Re-run initial allocation to refresh reports before bench allocation.'
                }

            return {
                'valid': True,
                'execution_id': validity_record.allocation_execution_id,
                'created_at': validity_record.created_datetime
            }

    except Exception as e:
        logger.error(f"Error validating allocation: {e}", exc_info=True)
        return {
            'valid': False,
            'error': f'Database error: {str(e)}'
        }


def get_validity_status(
    month: str,
    year: int,
    core_utils: CoreUtils
) -> Optional[Dict]:
    """
    Get current validity status for a month/year.

    Args:
        month: Month name (e.g., "January")
        year: Year (e.g., 2025)
        core_utils: CoreUtils instance for database access

    Returns:
        Dict with validity info or None if not found:
        - month: str
        - year: int
        - execution_id: str
        - is_valid: bool
        - created_datetime: datetime
        - invalidated_datetime: datetime (if applicable)
        - invalidated_reason: str (if applicable)
    """
    try:
        db_manager = core_utils.get_db_manager(AllocationValidityModel, limit=1, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            validity_record = session.query(AllocationValidityModel).filter(
                AllocationValidityModel.month == month,
                AllocationValidityModel.year == year
            ).first()

            if not validity_record:
                return None

            return {
                'month': validity_record.month,
                'year': validity_record.year,
                'execution_id': validity_record.allocation_execution_id,
                'is_valid': validity_record.is_valid,
                'created_datetime': validity_record.created_datetime,
                'invalidated_datetime': validity_record.invalidated_datetime,
                'invalidated_reason': validity_record.invalidated_reason
            }

    except Exception as e:
        logger.error(f"Error getting validity status: {e}", exc_info=True)
        return None
