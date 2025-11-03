"""
Utility functions for managing month configuration data.

This module provides functions to add, retrieve, update, and delete month-specific
configuration parameters that are used in FTE calculations and allocation logic.
"""

import logging
from typing import List, Dict, Optional, Tuple
import pandas as pd
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import and_

from code.logics.db import MonthConfigurationModel
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

# Initialize core utils for database operations (singleton for this module)
core_utils = CoreUtils(DATABASE_URL)


def add_month_configuration(
    month: str,
    year: int,
    work_type: str,
    working_days: int,
    occupancy: float,
    shrinkage: float,
    work_hours: int,
    created_by: str
) -> Tuple[bool, str]:
    """
    Add a single month configuration to the database.

    Args:
        month: Month name (e.g., "January", "February")
        year: Year (e.g., 2025)
        work_type: "Domestic" or "Global"
        working_days: Number of working days in the month
        occupancy: Occupancy rate (0.0 to 1.0, e.g., 0.95 for 95%)
        shrinkage: Shrinkage rate (0.0 to 1.0, e.g., 0.10 for 10%)
        work_hours: Work hours per day (e.g., 9)
        created_by: Username of the person creating the record

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        # Validate inputs
        if work_type not in ["Domestic", "Global"]:
            return False, f"Invalid work_type. Must be 'Domestic' or 'Global', got '{work_type}'"

        if not (0.0 <= occupancy <= 1.0):
            return False, f"Occupancy must be between 0.0 and 1.0, got {occupancy}"

        if not (0.0 <= shrinkage <= 1.0):
            return False, f"Shrinkage must be between 0.0 and 1.0, got {shrinkage}"

        if working_days <= 0:
            return False, f"Working days must be positive, got {working_days}"

        if work_hours <= 0:
            return False, f"Work hours must be positive, got {work_hours}"

        # PAIRING VALIDATION: Check if this configuration would orphan or be orphaned
        # For data integrity, both Domestic and Global must exist together for any month-year
        month_normalized = month.strip().capitalize()
        current_count = count_configs_for_month_year(month_normalized, year)

        if current_count == 1:
            # One config already exists - check if it's the opposite type
            pair_exists, opposite_type, _ = check_pair_exists(month_normalized, year, work_type)

            if not pair_exists:
                # The existing config is the SAME work type (shouldn't happen due to unique constraint)
                # But the opposite work type is missing - this would complete the pair, so allow it
                logger.info(f"Adding {work_type} for {month_normalized} {year} to complete the pair with {opposite_type}")
            else:
                # This is actually redundant due to unique constraint, but keep for clarity
                return False, f"Configuration for {month_normalized} {year} ({work_type}) already exists"

        elif current_count == 2:
            # Both configs already exist - this is a duplicate attempt
            return False, f"Both Domestic and Global configurations already exist for {month_normalized} {year}"

        # current_count == 0: First config for this month-year, allow it
        # This will be an orphan until the pair is added, but we allow starting the pair

        # Create DataFrame for database insertion
        df = pd.DataFrame([{
            'Month': month.strip().capitalize(),
            'Year': year,
            'WorkType': work_type,
            'WorkingDays': working_days,
            'Occupancy': occupancy,
            'Shrinkage': shrinkage,
            'WorkHours': work_hours,
            'CreatedBy': created_by,
            'UpdatedBy': created_by
        }])

        # Save to database
        db_manager = core_utils.get_db_manager(MonthConfigurationModel, limit=1, skip=0, select_columns=None)
        db_manager.save_to_db(df, replace=False)

        logger.info(f"Successfully added month configuration: {month} {year} - {work_type}")
        return True, f"Configuration for {month} {year} ({work_type}) added successfully"

    except IntegrityError as e:
        error_msg = f"Configuration for {month} {year} ({work_type}) already exists"
        logger.warning(error_msg)
        return False, error_msg

    except Exception as e:
        error_msg = f"Error adding month configuration: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


def bulk_add_month_configurations(
    configurations: List[Dict],
    created_by: str,
    skip_pairing_validation: bool = False
) -> Dict[str, any]:
    """
    Bulk add multiple month configurations.

    PAIRING VALIDATION: By default, validates that for each (month, year) in the batch,
    both Domestic and Global configurations are present. This ensures data integrity.

    Args:
        configurations: List of configuration dictionaries, each containing:
            - month: str
            - year: int
            - work_type: str
            - working_days: int
            - occupancy: float
            - shrinkage: float
            - work_hours: int
        created_by: Username of the person creating the records
        skip_pairing_validation: If True, skips batch pairing validation (default: False)
                                Use with caution - may create orphaned records

    Returns:
        Dictionary with keys:
            - total: Total number of configurations attempted
            - succeeded: Number of successful insertions
            - failed: Number of failed insertions
            - errors: List of error messages
            - validation_errors: List of pairing validation errors (if validation fails)
    """
    result = {
        'total': len(configurations),
        'succeeded': 0,
        'failed': 0,
        'errors': [],
        'validation_errors': []
    }

    # BATCH PAIRING VALIDATION
    if not skip_pairing_validation:
        # Group configurations by (month, year)
        month_year_groups = {}
        for config in configurations:
            try:
                month_key = config['month'].strip().capitalize()
                year_key = config['year']
                key = (month_key, year_key)

                if key not in month_year_groups:
                    month_year_groups[key] = set()

                month_year_groups[key].add(config['work_type'])
            except KeyError as e:
                result['validation_errors'].append(f"Missing required field in config: {str(e)}")

        # Validate each group has both Domestic and Global
        incomplete_pairs = []
        for (month, year), work_types in month_year_groups.items():
            if len(work_types) != 2 or work_types != {'Domestic', 'Global'}:
                missing = {'Domestic', 'Global'} - work_types
                incomplete_pairs.append({
                    'month': month,
                    'year': year,
                    'has': list(work_types),
                    'missing': list(missing)
                })

        if incomplete_pairs:
            # Build detailed error message
            error_details = []
            for pair in incomplete_pairs:
                error_details.append(
                    f"  - {pair['month']} {pair['year']}: Has {', '.join(pair['has'])}, "
                    f"missing {', '.join(pair['missing'])}"
                )

            result['validation_errors'].append(
                "Batch validation failed: Missing pairs for the following month-years:\n" +
                "\n".join(error_details)
            )
            result['failed'] = result['total']
            logger.error(f"Bulk add validation failed: {len(incomplete_pairs)} incomplete pairs")
            return result

        logger.info(f"Batch pairing validation passed: {len(month_year_groups)} complete pairs")

    # Proceed with insertion
    for config in configurations:
        try:
            success, message = add_month_configuration(
                month=config['month'],
                year=config['year'],
                work_type=config['work_type'],
                working_days=config['working_days'],
                occupancy=config['occupancy'],
                shrinkage=config['shrinkage'],
                work_hours=config['work_hours'],
                created_by=created_by
            )

            if success:
                result['succeeded'] += 1
            else:
                result['failed'] += 1
                result['errors'].append(f"{config['month']} {config['year']} ({config['work_type']}): {message}")

        except KeyError as e:
            result['failed'] += 1
            result['errors'].append(f"Missing required field: {str(e)}")
            logger.error(f"Missing required field in configuration: {e}")

        except Exception as e:
            result['failed'] += 1
            result['errors'].append(f"Unexpected error: {str(e)}")
            logger.error(f"Error in bulk add: {e}", exc_info=True)

    logger.info(f"Bulk add completed: {result['succeeded']} succeeded, {result['failed']} failed")
    return result


def get_month_configuration(
    month: Optional[str] = None,
    year: Optional[int] = None,
    work_type: Optional[str] = None
) -> List[Dict]:
    """
    Retrieve month configurations with optional filters.

    Args:
        month: Optional month filter (e.g., "January")
        year: Optional year filter (e.g., 2025)
        work_type: Optional work type filter ("Domestic" or "Global")

    Returns:
        List of configuration dictionaries
    """
    try:
        db_manager = core_utils.get_db_manager(MonthConfigurationModel, limit=1000, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            query = session.query(MonthConfigurationModel)

            # Apply filters
            if month:
                query = query.filter(MonthConfigurationModel.Month == month.strip().capitalize())
            if year:
                query = query.filter(MonthConfigurationModel.Year == year)
            if work_type:
                query = query.filter(MonthConfigurationModel.WorkType == work_type)

            # Order by year, month, work type
            query = query.order_by(
                MonthConfigurationModel.Year.desc(),
                MonthConfigurationModel.Month,
                MonthConfigurationModel.WorkType
            )

            results = query.all()

            # Convert to dictionaries
            configs = []
            for record in results:
                configs.append({
                    'id': record.id,
                    'month': record.Month,
                    'year': record.Year,
                    'work_type': record.WorkType,
                    'working_days': record.WorkingDays,
                    'occupancy': record.Occupancy,
                    'shrinkage': record.Shrinkage,
                    'work_hours': record.WorkHours,
                    'created_by': record.CreatedBy,
                    'updated_by': record.UpdatedBy,
                    'created_datetime': record.CreatedDateTime.isoformat() if record.CreatedDateTime else None,
                    'updated_datetime': record.UpdatedDateTime.isoformat() if record.UpdatedDateTime else None
                })

            logger.info(f"Retrieved {len(configs)} month configurations")
            return configs

    except Exception as e:
        logger.error(f"Error retrieving month configurations: {e}", exc_info=True)
        return []


def get_specific_config(month: str, year: int, work_type: str) -> Optional[Dict]:
    """
    Get a specific month configuration.

    Args:
        month: Month name (e.g., "January")
        year: Year (e.g., 2025)
        work_type: "Domestic" or "Global"

    Returns:
        Configuration dictionary or None if not found
    """
    configs = get_month_configuration(month=month, year=year, work_type=work_type)
    return configs[0] if configs else None


def check_pair_exists(month: str, year: int, work_type: str) -> Tuple[bool, str, Optional[Dict]]:
    """
    Check if the opposite work type configuration exists for the same month-year.

    This is used to enforce pairing validation: both Domestic and Global must exist
    together for any month-year combination.

    Args:
        month: Month name (e.g., "January")
        year: Year (e.g., 2025)
        work_type: Work type being added/checked ("Domestic" or "Global")

    Returns:
        Tuple of:
            - exists: bool - True if opposite work type exists
            - opposite_type: str - Name of the opposite work type
            - config: Optional[Dict] - The opposite config if it exists, None otherwise
    """
    opposite_type = 'Global' if work_type == 'Domestic' else 'Domestic'
    config = get_specific_config(month, year, opposite_type)
    exists = config is not None

    return exists, opposite_type, config


def count_configs_for_month_year(month: str, year: int) -> int:
    """
    Count how many configurations exist for a specific month-year.

    Used to detect if a month-year has partial data (only Domestic or only Global).

    Args:
        month: Month name (e.g., "January")
        year: Year (e.g., 2025)

    Returns:
        Count of configurations (should be 0 or 2 for valid data)
    """
    configs = get_month_configuration(month=month, year=year)
    return len(configs)


def update_month_configuration(
    config_id: int,
    working_days: Optional[int] = None,
    occupancy: Optional[float] = None,
    shrinkage: Optional[float] = None,
    work_hours: Optional[int] = None,
    updated_by: str = "System"
) -> Tuple[bool, str]:
    """
    Update an existing month configuration.

    Args:
        config_id: ID of the configuration to update
        working_days: New working days value (optional)
        occupancy: New occupancy value (optional)
        shrinkage: New shrinkage value (optional)
        work_hours: New work hours value (optional)
        updated_by: Username of the person updating the record

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        db_manager = core_utils.get_db_manager(MonthConfigurationModel, limit=1, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            config = session.query(MonthConfigurationModel).filter(MonthConfigurationModel.id == config_id).first()

            if not config:
                return False, f"Configuration with ID {config_id} not found"

            # Update fields if provided
            if working_days is not None:
                if working_days <= 0:
                    return False, f"Working days must be positive, got {working_days}"
                config.WorkingDays = working_days

            if occupancy is not None:
                if not (0.0 <= occupancy <= 1.0):
                    return False, f"Occupancy must be between 0.0 and 1.0, got {occupancy}"
                config.Occupancy = occupancy

            if shrinkage is not None:
                if not (0.0 <= shrinkage <= 1.0):
                    return False, f"Shrinkage must be between 0.0 and 1.0, got {shrinkage}"
                config.Shrinkage = shrinkage

            if work_hours is not None:
                if work_hours <= 0:
                    return False, f"Work hours must be positive, got {work_hours}"
                config.WorkHours = work_hours

            config.UpdatedBy = updated_by

            session.commit()

            logger.info(f"Successfully updated configuration ID {config_id}")
            return True, f"Configuration updated successfully"

    except Exception as e:
        error_msg = f"Error updating configuration: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


def delete_month_configuration(config_id: int, allow_orphan: bool = False) -> Tuple[bool, str]:
    """
    Delete a month configuration.

    ORPHAN PREVENTION: By default, prevents deletion if it would leave an orphaned
    record (month-year with only Domestic or only Global). This ensures data integrity.

    Args:
        config_id: ID of the configuration to delete
        allow_orphan: If True, allows deletion even if it orphans the pair (default: False)
                     Use with caution - may create inconsistent calculation behavior

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        db_manager = core_utils.get_db_manager(MonthConfigurationModel, limit=1, skip=0, select_columns=None)

        with db_manager.SessionLocal() as session:
            config = session.query(MonthConfigurationModel).filter(MonthConfigurationModel.id == config_id).first()

            if not config:
                return False, f"Configuration with ID {config_id} not found"

            # PAIRING VALIDATION: Check if deletion would orphan a record
            if not allow_orphan:
                month = config.Month
                year = config.Year
                work_type = config.WorkType

                # Check if opposite work type exists
                pair_exists, opposite_type, opposite_config = check_pair_exists(month, year, work_type)

                if pair_exists:
                    # Deleting this would orphan the opposite config
                    opposite_id = opposite_config['id']
                    error_msg = (
                        f"Cannot delete {work_type} configuration for {month} {year} (ID: {config_id}). "
                        f"This would orphan the {opposite_type} configuration (ID: {opposite_id}). "
                        f"Please delete both configurations together, or set allow_orphan=True to force deletion."
                    )
                    logger.warning(error_msg)
                    return False, error_msg

            # Proceed with deletion
            session.delete(config)
            session.commit()

            logger.info(f"Successfully deleted configuration ID {config_id}")
            return True, f"Configuration deleted successfully"

    except Exception as e:
        error_msg = f"Error deleting configuration: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


def validate_all_pairs() -> Dict[str, any]:
    """
    Validate data integrity by finding orphaned configurations.

    An orphaned configuration is one where a month-year has only Domestic OR only Global,
    but not both. This violates the pairing rule and causes inconsistent calculations.

    Returns:
        Dictionary with keys:
            - is_valid: bool - True if all configurations are properly paired
            - orphaned_records: List of orphaned configuration details
            - total_configs: Total number of configurations in database
            - paired_count: Number of properly paired month-years
            - orphaned_count: Number of orphaned configurations
            - recommendations: List of suggested actions to fix issues
    """
    try:
        # Get all configurations
        all_configs = get_month_configuration()

        # Group by (month, year)
        month_year_groups = {}
        for config in all_configs:
            key = (config['month'], config['year'])
            if key not in month_year_groups:
                month_year_groups[key] = []
            month_year_groups[key].append(config)

        # Find orphaned records
        orphaned_records = []
        properly_paired = 0

        for (month, year), configs in month_year_groups.items():
            if len(configs) == 1:
                # Orphaned - only one work type exists
                orphan = configs[0]
                missing_type = 'Global' if orphan['work_type'] == 'Domestic' else 'Domestic'

                orphaned_records.append({
                    'month': month,
                    'year': year,
                    'existing_type': orphan['work_type'],
                    'existing_id': orphan['id'],
                    'missing_type': missing_type,
                    'working_days': orphan['working_days'],
                    'occupancy': orphan['occupancy'],
                    'shrinkage': orphan['shrinkage'],
                    'work_hours': orphan['work_hours']
                })
            elif len(configs) == 2:
                # Properly paired
                work_types = {c['work_type'] for c in configs}
                if work_types == {'Domestic', 'Global'}:
                    properly_paired += 1
                else:
                    # Duplicate of same type (shouldn't happen due to unique constraint)
                    logger.warning(f"Found duplicate work types for {month} {year}: {work_types}")

        # Build recommendations
        recommendations = []
        if orphaned_records:
            recommendations.append(
                f"Found {len(orphaned_records)} orphaned configuration(s). "
                "Add the missing work type for each month-year to fix."
            )
            recommendations.append(
                "Use POST /api/month-config to add missing configurations, or "
                "DELETE /api/month-config/{id} to remove orphaned records."
            )

        result = {
            'is_valid': len(orphaned_records) == 0,
            'orphaned_records': orphaned_records,
            'total_configs': len(all_configs),
            'paired_count': properly_paired,
            'orphaned_count': len(orphaned_records),
            'recommendations': recommendations
        }

        if result['is_valid']:
            logger.info(f"Validation passed: All {properly_paired} month-years are properly paired")
        else:
            logger.warning(f"Validation failed: Found {len(orphaned_records)} orphaned records")

        return result

    except Exception as e:
        logger.error(f"Error validating pairs: {e}", exc_info=True)
        return {
            'is_valid': False,
            'error': str(e),
            'orphaned_records': [],
            'total_configs': 0,
            'paired_count': 0,
            'orphaned_count': 0,
            'recommendations': ['Error occurred during validation. Check logs for details.']
        }


def seed_initial_data(base_year: int = 2025, num_years: int = 2, created_by: str = "System") -> Dict[str, any]:
    """
    Seed the database with initial month configuration data.

    Creates configurations for all 12 months for the specified number of years,
    for both Domestic and Global work types.

    Default values based on the calculations.xlsx:
    - Occupancy: 95% (0.95)
    - Shrinkage: 10% (0.10)
    - Work Hours: 9
    - Working Days: Varies by month

    Args:
        base_year: Starting year for seed data (default: 2025)
        num_years: Number of years to seed (default: 2)
        created_by: Username for audit trail

    Returns:
        Dictionary with seeding results
    """
    # Default working days per month (based on typical calendar)
    default_working_days = {
        'January': 21,
        'February': 20,
        'March': 21,
        'April': 21,
        'May': 21,
        'June': 21,
        'July': 22,
        'August': 22,
        'September': 21,
        'October': 21,
        'November': 21,
        'December': 21
    }

    # Default parameters from calculations.xlsx
    default_params = {
        'occupancy': 0.95,
        'shrinkage': 0.10,
        'work_hours': 9
    }

    configurations = []

    # Generate configurations for all months, years, and work types
    for year_offset in range(num_years):
        year = base_year + year_offset
        for month, working_days in default_working_days.items():
            for work_type in ['Domestic', 'Global']:
                configurations.append({
                    'month': month,
                    'year': year,
                    'work_type': work_type,
                    'working_days': working_days,
                    'occupancy': default_params['occupancy'],
                    'shrinkage': default_params['shrinkage'],
                    'work_hours': default_params['work_hours']
                })

    # Bulk add all configurations
    result = bulk_add_month_configurations(configurations, created_by)

    logger.info(f"Seed data operation completed: {result['succeeded']}/{result['total']} configurations added")
    return result
