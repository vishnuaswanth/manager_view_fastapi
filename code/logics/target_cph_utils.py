"""
Utility functions for managing Target CPH configuration data.

This module provides functions to add, retrieve, update, and delete Target CPH
configuration parameters that are used in allocation logic for FTE calculations.

Target CPH (Cases Per Hour) values are specific to Main LOB and Case Type combinations.
"""

import logging
from typing import List, Dict, Optional, Tuple
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import and_

from code.logics.db import TargetCPHModel
from code.api.dependencies import get_core_utils

logger = logging.getLogger(__name__)


# Validation constants
MIN_TARGET_CPH = 0.1
MAX_TARGET_CPH = 200.0
MAX_LOB_LENGTH = 255
MAX_CASE_TYPE_LENGTH = 255


def _validate_target_cph_input(
    main_lob: str,
    case_type: str,
    target_cph: float
) -> Tuple[bool, str]:
    """
    Validate Target CPH configuration input parameters.

    Args:
        main_lob: Main line of business
        case_type: Case type identifier
        target_cph: Target CPH value

    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    # Validate MainLOB
    if not main_lob or not main_lob.strip():
        return False, "MainLOB cannot be empty"

    if len(main_lob.strip()) > MAX_LOB_LENGTH:
        return False, f"MainLOB exceeds maximum length of {MAX_LOB_LENGTH} characters"

    # Validate CaseType
    if not case_type or not case_type.strip():
        return False, "CaseType cannot be empty"

    if len(case_type.strip()) > MAX_CASE_TYPE_LENGTH:
        return False, f"CaseType exceeds maximum length of {MAX_CASE_TYPE_LENGTH} characters"

    # Validate TargetCPH
    if not isinstance(target_cph, (int, float)):
        return False, f"TargetCPH must be a number, got {type(target_cph).__name__}"

    if target_cph < MIN_TARGET_CPH:
        return False, f"TargetCPH must be at least {MIN_TARGET_CPH}, got {target_cph}"

    if target_cph > MAX_TARGET_CPH:
        return False, f"TargetCPH cannot exceed {MAX_TARGET_CPH}, got {target_cph}"

    return True, ""


def add_target_cph_configuration(
    main_lob: str,
    case_type: str,
    target_cph: float,
    created_by: str
) -> Tuple[bool, str]:
    """
    Add a single Target CPH configuration to the database.

    Args:
        main_lob: Main line of business (e.g., "Amisys Medicaid GLOBAL")
        case_type: Case type identifier (e.g., "FTC-Basic/Non MMP")
        target_cph: Target cases per hour value (e.g., 12.0)
        created_by: Username of the person creating the record

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        # Validate inputs
        is_valid, error_msg = _validate_target_cph_input(main_lob, case_type, target_cph)
        if not is_valid:
            return False, error_msg

        # Normalize inputs
        main_lob_normalized = main_lob.strip()
        case_type_normalized = case_type.strip()

        core_utils = get_core_utils()
        db_manager = core_utils.get_db_manager(TargetCPHModel, limit=1, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            # Check if configuration already exists
            existing = session.query(TargetCPHModel).filter(
                and_(
                    TargetCPHModel.MainLOB == main_lob_normalized,
                    TargetCPHModel.CaseType == case_type_normalized
                )
            ).first()

            if existing:
                return False, f"Configuration for MainLOB='{main_lob_normalized}', CaseType='{case_type_normalized}' already exists (ID: {existing.id})"

            # Create new record
            new_config = TargetCPHModel(
                MainLOB=main_lob_normalized,
                CaseType=case_type_normalized,
                TargetCPH=float(target_cph),
                CreatedBy=created_by.strip(),
                UpdatedBy=created_by.strip()
            )

            session.add(new_config)
            session.commit()

            logger.info(f"Successfully added Target CPH configuration: MainLOB='{main_lob_normalized}', CaseType='{case_type_normalized}', TargetCPH={target_cph}")
            return True, f"Configuration added successfully (ID: {new_config.id})"

    except IntegrityError as e:
        error_msg = f"Configuration for MainLOB='{main_lob}', CaseType='{case_type}' already exists"
        logger.warning(error_msg)
        return False, error_msg

    except Exception as e:
        error_msg = f"Error adding Target CPH configuration: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


def bulk_add_target_cph_configurations(
    configurations: List[Dict],
    created_by: str = None
) -> Dict:
    """
    Bulk add multiple Target CPH configurations.

    Args:
        configurations: List of configuration dictionaries, each containing:
            - main_lob: str
            - case_type: str
            - target_cph: float
            - created_by: str (optional, uses parameter if not in dict)
        created_by: Default username if not specified in individual configs

    Returns:
        Dictionary with keys:
            - total: Total number of configurations attempted
            - succeeded: Number of successful insertions
            - failed: Number of failed insertions
            - errors: List of error messages
            - duplicates_skipped: Count of duplicates skipped
    """
    result = {
        'total': len(configurations),
        'succeeded': 0,
        'failed': 0,
        'errors': [],
        'duplicates_skipped': 0
    }

    for i, config in enumerate(configurations):
        try:
            # Get values from config dict
            main_lob = config.get('main_lob', '').strip()
            case_type = config.get('case_type', '').strip()
            target_cph = config.get('target_cph')
            user = config.get('created_by', created_by)

            if not user:
                result['failed'] += 1
                result['errors'].append(f"Config {i+1}: Missing created_by")
                continue

            success, message = add_target_cph_configuration(
                main_lob=main_lob,
                case_type=case_type,
                target_cph=target_cph,
                created_by=user
            )

            if success:
                result['succeeded'] += 1
            else:
                if 'already exists' in message.lower():
                    result['duplicates_skipped'] += 1
                else:
                    result['failed'] += 1
                    result['errors'].append(f"Config {i+1} ({main_lob}/{case_type}): {message}")

        except KeyError as e:
            result['failed'] += 1
            result['errors'].append(f"Config {i+1}: Missing required field: {str(e)}")
            logger.error(f"Missing required field in configuration: {e}")

        except Exception as e:
            result['failed'] += 1
            result['errors'].append(f"Config {i+1}: Unexpected error: {str(e)}")
            logger.error(f"Error in bulk add: {e}", exc_info=True)

    logger.info(f"Bulk add completed: {result['succeeded']} succeeded, {result['failed']} failed, {result['duplicates_skipped']} duplicates skipped")
    return result


def get_target_cph_configuration(
    main_lob: Optional[str] = None,
    case_type: Optional[str] = None,
    config_id: Optional[int] = None
) -> List[Dict]:
    """
    Retrieve Target CPH configurations with optional filters.

    Args:
        main_lob: Optional Main LOB filter (partial match, case-insensitive)
        case_type: Optional Case Type filter (partial match, case-insensitive)
        config_id: Optional specific configuration ID

    Returns:
        List of configuration dictionaries
    """
    try:
        core_utils = get_core_utils()
        db_manager = core_utils.get_db_manager(TargetCPHModel, limit=1000, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            query = session.query(TargetCPHModel)

            # Apply filters
            if config_id:
                query = query.filter(TargetCPHModel.id == config_id)

            if main_lob:
                # Case-insensitive partial match
                query = query.filter(TargetCPHModel.MainLOB.ilike(f"%{main_lob.strip()}%"))

            if case_type:
                # Case-insensitive partial match
                query = query.filter(TargetCPHModel.CaseType.ilike(f"%{case_type.strip()}%"))

            # Order by MainLOB, then CaseType
            query = query.order_by(
                TargetCPHModel.MainLOB,
                TargetCPHModel.CaseType
            )

            results = query.all()

            # Convert to dictionaries
            configs = []
            for record in results:
                configs.append({
                    'id': record.id,
                    'main_lob': record.MainLOB,
                    'case_type': record.CaseType,
                    'target_cph': record.TargetCPH,
                    'created_by': record.CreatedBy,
                    'updated_by': record.UpdatedBy,
                    'created_datetime': record.CreatedDateTime.isoformat() if record.CreatedDateTime else None,
                    'updated_datetime': record.UpdatedDateTime.isoformat() if record.UpdatedDateTime else None
                })

            logger.info(f"Retrieved {len(configs)} Target CPH configurations")
            return configs

    except Exception as e:
        logger.error(f"Error retrieving Target CPH configurations: {e}", exc_info=True)
        return []


def get_all_target_cph_as_dict() -> Dict[Tuple[str, str], float]:
    """
    Load all Target CPH configurations into memory for efficient batch lookups.

    This function performs a single database query and returns a dictionary
    keyed by (main_lob_lower, case_type_lower) tuples for O(1) lookups.

    Used by Calculations class in allocation.py for efficient per-row lookups.

    Returns:
        Dictionary with (main_lob_lower, case_type_lower) -> target_cph
        Keys are lowercased and stripped for case-insensitive matching.

    Example:
        >>> lookup = get_all_target_cph_as_dict()
        >>> cph = lookup.get(("amisys medicaid global", "ftc-basic/non mmp"), 0.0)
        >>> print(cph)
        12.0
    """
    try:
        core_utils = get_core_utils()
        db_manager = core_utils.get_db_manager(TargetCPHModel, limit=10000, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            results = session.query(
                TargetCPHModel.MainLOB,
                TargetCPHModel.CaseType,
                TargetCPHModel.TargetCPH
            ).all()

            # Build lookup dictionary with normalized keys
            lookup = {}
            for main_lob, case_type, target_cph in results:
                key = (main_lob.strip().lower(), case_type.strip().lower())
                lookup[key] = float(target_cph)

            logger.info(f"Loaded {len(lookup)} Target CPH configurations into memory")
            return lookup

    except Exception as e:
        logger.error(f"Error loading Target CPH configurations: {e}", exc_info=True)
        return {}


def get_specific_target_cph(main_lob: str, case_type: str) -> Optional[float]:
    """
    Get Target CPH for a specific Main LOB and Case Type combination.

    Args:
        main_lob: Main line of business (exact match, case-insensitive)
        case_type: Case type (exact match, case-insensitive)

    Returns:
        Target CPH value, or None if not found
    """
    try:
        core_utils = get_core_utils()
        db_manager = core_utils.get_db_manager(TargetCPHModel, limit=1, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            # Use case-insensitive exact match (normalized)
            from sqlalchemy import func
            result = session.query(TargetCPHModel).filter(
                and_(
                    func.lower(func.trim(TargetCPHModel.MainLOB)) == main_lob.strip().lower(),
                    func.lower(func.trim(TargetCPHModel.CaseType)) == case_type.strip().lower()
                )
            ).first()

            if result:
                return result.TargetCPH
            else:
                return None

    except Exception as e:
        logger.error(f"Error getting specific Target CPH: {e}", exc_info=True)
        return None


def update_target_cph_configuration(
    config_id: int,
    target_cph: Optional[float] = None,
    main_lob: Optional[str] = None,
    case_type: Optional[str] = None,
    updated_by: str = "System"
) -> Tuple[bool, str]:
    """
    Update an existing Target CPH configuration.

    Args:
        config_id: ID of the configuration to update
        target_cph: New Target CPH value (optional)
        main_lob: New Main LOB value (optional)
        case_type: New Case Type value (optional)
        updated_by: Username of the person updating the record

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        core_utils = get_core_utils()
        db_manager = core_utils.get_db_manager(TargetCPHModel, limit=1, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            config = session.query(TargetCPHModel).filter(TargetCPHModel.id == config_id).first()

            if not config:
                return False, f"Configuration with ID {config_id} not found"

            # Track if any changes were made
            changes_made = False

            # Update target_cph if provided
            if target_cph is not None:
                if target_cph < MIN_TARGET_CPH:
                    return False, f"TargetCPH must be at least {MIN_TARGET_CPH}, got {target_cph}"
                if target_cph > MAX_TARGET_CPH:
                    return False, f"TargetCPH cannot exceed {MAX_TARGET_CPH}, got {target_cph}"
                config.TargetCPH = float(target_cph)
                changes_made = True

            # Update main_lob if provided
            if main_lob is not None:
                if not main_lob.strip():
                    return False, "MainLOB cannot be empty"
                if len(main_lob.strip()) > MAX_LOB_LENGTH:
                    return False, f"MainLOB exceeds maximum length of {MAX_LOB_LENGTH} characters"
                config.MainLOB = main_lob.strip()
                changes_made = True

            # Update case_type if provided
            if case_type is not None:
                if not case_type.strip():
                    return False, "CaseType cannot be empty"
                if len(case_type.strip()) > MAX_CASE_TYPE_LENGTH:
                    return False, f"CaseType exceeds maximum length of {MAX_CASE_TYPE_LENGTH} characters"
                config.CaseType = case_type.strip()
                changes_made = True

            if not changes_made:
                return False, "No changes provided"

            config.UpdatedBy = updated_by.strip()

            session.commit()

            logger.info(f"Successfully updated Target CPH configuration ID {config_id}")
            return True, "Configuration updated successfully"

    except IntegrityError as e:
        error_msg = f"Update would create duplicate: MainLOB and CaseType combination already exists"
        logger.warning(error_msg)
        return False, error_msg

    except Exception as e:
        error_msg = f"Error updating configuration: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


def delete_target_cph_configuration(config_id: int) -> Tuple[bool, str]:
    """
    Delete a Target CPH configuration.

    Args:
        config_id: ID of the configuration to delete

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        core_utils = get_core_utils()
        db_manager = core_utils.get_db_manager(TargetCPHModel, limit=1, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            config = session.query(TargetCPHModel).filter(TargetCPHModel.id == config_id).first()

            if not config:
                return False, f"Configuration with ID {config_id} not found"

            # Store info for logging
            main_lob = config.MainLOB
            case_type = config.CaseType

            session.delete(config)
            session.commit()

            logger.info(f"Successfully deleted Target CPH configuration ID {config_id} (MainLOB='{main_lob}', CaseType='{case_type}')")
            return True, "Configuration deleted successfully"

    except Exception as e:
        error_msg = f"Error deleting configuration: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


def get_target_cph_count() -> int:
    """
    Get the total count of Target CPH configurations.

    Returns:
        Total count of configurations
    """
    try:
        core_utils = get_core_utils()
        db_manager = core_utils.get_db_manager(TargetCPHModel, limit=1, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            count = session.query(TargetCPHModel).count()
            return count

    except Exception as e:
        logger.error(f"Error getting Target CPH count: {e}", exc_info=True)
        return 0


def get_distinct_main_lobs() -> List[str]:
    """
    Get list of distinct Main LOB values.

    Returns:
        Sorted list of distinct Main LOB values
    """
    try:
        core_utils = get_core_utils()
        db_manager = core_utils.get_db_manager(TargetCPHModel, limit=1000, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            from sqlalchemy import func
            results = session.query(func.distinct(TargetCPHModel.MainLOB)).order_by(TargetCPHModel.MainLOB).all()
            return [r[0] for r in results if r[0]]

    except Exception as e:
        logger.error(f"Error getting distinct Main LOBs: {e}", exc_info=True)
        return []


def get_distinct_case_types(main_lob: Optional[str] = None) -> List[str]:
    """
    Get list of distinct Case Type values, optionally filtered by Main LOB.

    Args:
        main_lob: Optional Main LOB filter

    Returns:
        Sorted list of distinct Case Type values
    """
    try:
        core_utils = get_core_utils()
        db_manager = core_utils.get_db_manager(TargetCPHModel, limit=1000, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            from sqlalchemy import func
            query = session.query(func.distinct(TargetCPHModel.CaseType))

            if main_lob:
                query = query.filter(TargetCPHModel.MainLOB.ilike(f"%{main_lob.strip()}%"))

            results = query.order_by(TargetCPHModel.CaseType).all()
            return [r[0] for r in results if r[0]]

    except Exception as e:
        logger.error(f"Error getting distinct Case Types: {e}", exc_info=True)
        return []
