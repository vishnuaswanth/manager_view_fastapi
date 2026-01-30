"""
FTE Allocation Mapping Utilities

This module provides functions to populate and query the FTEAllocationMappingModel table,
which stores denormalized FTE-to-forecast mappings for fast LLM querying.

Data is cleared and replaced when allocation runs - no historical preservation.
"""

import logging
import calendar
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import and_
from sqlalchemy.exc import SQLAlchemyError

from code.logics.db import FTEAllocationMappingModel
from code.logics.bench_allocation import parse_vendor_skills
from code.api.dependencies import get_core_utils, get_logger

logger = get_logger(__name__)


def _get_month_label(month_name: str, year: int) -> str:
    """
    Convert month name and year to label format (e.g., "Apr-25").

    Args:
        month_name: Full month name (e.g., "April")
        year: Year (e.g., 2025)

    Returns:
        Month label (e.g., "Apr-25")
    """
    month_abbr_map = {
        "January": "Jan",
        "February": "Feb",
        "March": "Mar",
        "April": "Apr",
        "May": "May",
        "June": "Jun",
        "July": "Jul",
        "August": "Aug",
        "September": "Sep",
        "October": "Oct",
        "November": "Nov",
        "December": "Dec"
    }

    abbr = month_abbr_map.get(month_name, month_name[:3])
    year_short = str(year)[2:]  # Last 2 digits

    return f"{abbr}-{year_short}"


def _get_year_for_month(report_month: str, report_year: int, forecast_month: str) -> int:
    """
    Calculate the correct year for a forecast month in a consecutive 6-month sequence.

    When the 6 forecast months wrap from December into January, this function
    determines the correct year to use.

    Args:
        report_month: The report month (e.g., "March")
        report_year: The year of the report month (e.g., 2025)
        forecast_month: The forecast month we need to determine the year for (e.g., "January")

    Returns:
        The correct year for the forecast_month
    """
    month_to_num = {month: idx for idx, month in enumerate(calendar.month_name) if month}

    report_month_num = month_to_num.get(report_month, 1)
    forecast_month_num = month_to_num.get(forecast_month, 1)

    return report_year + 1 if forecast_month_num < report_month_num else report_year


def _get_month_index(month_headers: List[str], month_name: str) -> int:
    """
    Get the month index (1-6) for a given month name within the month_headers list.

    Args:
        month_headers: List of month names (e.g., ["April", "May", "June", "July", "August", "September"])
        month_name: Month name to find

    Returns:
        Month index (1-6) or 0 if not found
    """
    try:
        return month_headers.index(month_name) + 1
    except ValueError:
        return 0


def clear_fte_mappings(
    month: str,
    year: int,
    allocation_type: str,
    core_utils: Any
) -> int:
    """
    Clear existing FTE mappings for a given report month/year and allocation type.

    Args:
        month: Report month (e.g., "March")
        year: Report year (e.g., 2025)
        allocation_type: 'primary' or 'bench'
        core_utils: CoreUtils instance

    Returns:
        Number of records deleted
    """
    db_manager = core_utils.get_db_manager(
        FTEAllocationMappingModel,
        limit=None,
        skip=0,
        select_columns=None
    )

    try:
        with db_manager.SessionLocal() as session:
            deleted_count = session.query(FTEAllocationMappingModel).filter(
                and_(
                    FTEAllocationMappingModel.report_month == month,
                    FTEAllocationMappingModel.report_year == year,
                    FTEAllocationMappingModel.allocation_type == allocation_type
                )
            ).delete(synchronize_session=False)

            session.commit()

            logger.info(
                f"Cleared {deleted_count} existing FTE mappings for "
                f"{month} {year} ({allocation_type})"
            )
            return deleted_count

    except SQLAlchemyError as e:
        logger.error(f"Failed to clear FTE mappings: {e}", exc_info=True)
        return 0


def populate_fte_mapping_from_primary(
    execution_id: str,
    month: str,
    year: int,
    vendor_allocations: Dict[str, Dict[str, Dict[str, str]]],
    vendor_df: pd.DataFrame,
    month_headers: List[str],
    worktype_vocab: List[str],
    core_utils: Any
) -> int:
    """
    Populate FTE mappings from primary allocation results.

    Clears existing primary mappings for (month, year) before inserting new ones.

    Args:
        execution_id: Allocation execution ID
        month: Report month (e.g., "March")
        year: Report year (e.g., 2025)
        vendor_allocations: Dict mapping CN# -> {month: allocation_details}
                           allocation_details has: platform (main_lob), state, worktype
        vendor_df: Original vendor DataFrame with vendor details
        month_headers: List of month names (e.g., ["April", "May", ...])
        worktype_vocab: List of valid worktypes for skill parsing (sorted longest-first)
        core_utils: CoreUtils instance

    Returns:
        Number of records inserted
    """
    logger.info(f"Populating FTE mappings from primary allocation for {month} {year}...")

    # Clear existing primary mappings
    clear_fte_mappings(month, year, 'primary', core_utils)

    if not vendor_allocations:
        logger.info("No vendor allocations to populate")
        return 0

    db_manager = core_utils.get_db_manager(
        FTEAllocationMappingModel,
        limit=None,
        skip=0,
        select_columns=None
    )

    records_to_insert = []

    for cn, month_allocations in vendor_allocations.items():
        # Get vendor details from DataFrame using CN# as key
        # CN# is a stable identifier (DataFrame indices become unreliable after filtering)
        vendor_matches = vendor_df[vendor_df['CN'].astype(str) == str(cn)]
        if vendor_matches.empty:
            logger.warning(f"Vendor CN {cn} not found in vendor_df")
            continue
        vendor_row = vendor_matches.iloc[0]

        # CN is already known from the loop
        if not cn:
            continue

        first_name = str(vendor_row.get('FirstName', ''))
        last_name = str(vendor_row.get('LastName', ''))
        opid = str(vendor_row.get('OPID', ''))
        primary_platform = str(vendor_row.get('PrimaryPlatform', ''))
        primary_market = str(vendor_row.get('PrimaryMarket', ''))
        location = str(vendor_row.get('Location', ''))
        original_state = str(vendor_row.get('State', ''))
        worktype_from_roster = str(vendor_row.get('NewWorkType', ''))

        # Parse skills from NewWorkType using vocabulary
        parsed_skills = parse_vendor_skills(worktype_from_roster, worktype_vocab)
        skills_str = ', '.join(sorted(parsed_skills)) if parsed_skills else ''

        # Process each month allocation
        for forecast_month, allocation_details in month_allocations.items():
            main_lob = allocation_details.get('platform', '')
            state = allocation_details.get('state', '')
            case_type = allocation_details.get('worktype', '')

            # Calculate forecast year and month label
            forecast_year = _get_year_for_month(month, year, forecast_month)
            forecast_month_label = _get_month_label(forecast_month, forecast_year)
            month_index = _get_month_index(month_headers, forecast_month)

            record = FTEAllocationMappingModel(
                allocation_execution_id=execution_id,
                report_month=month,
                report_year=year,
                main_lob=main_lob,
                state=state,
                case_type=case_type,
                call_type_id='',  # Not available in primary allocation data
                forecast_month=forecast_month,
                forecast_year=forecast_year,
                forecast_month_label=forecast_month_label,
                forecast_month_index=month_index,
                cn=cn,
                first_name=first_name,
                last_name=last_name,
                opid=opid,
                primary_platform=primary_platform,
                primary_market=primary_market,
                location=location,
                original_state=original_state,
                worktype=worktype_from_roster,
                new_work_type=worktype_from_roster,
                skills=skills_str,
                allocation_type='primary'
            )
            records_to_insert.append(record)

    if not records_to_insert:
        logger.info("No FTE mapping records to insert")
        return 0

    try:
        with db_manager.SessionLocal() as session:
            session.add_all(records_to_insert)
            session.commit()

            logger.info(f"Inserted {len(records_to_insert)} FTE mapping records (primary)")
            return len(records_to_insert)

    except SQLAlchemyError as e:
        logger.error(f"Failed to insert FTE mappings: {e}", exc_info=True)
        return 0


def populate_fte_mapping_from_bench(
    execution_id: str,
    month: str,
    year: int,
    consolidated_changes: Dict,
    worktype_vocab: List[str],
    core_utils: Any
) -> int:
    """
    Populate FTE mappings from bench allocation results.

    Clears existing bench mappings for (month, year) before inserting new ones.

    Args:
        execution_id: Allocation execution ID
        month: Report month (e.g., "March")
        year: Report year (e.g., 2025)
        consolidated_changes: Dict mapping (forecast_id, month_index) -> change_data
                             change_data has: forecast_row (ForecastRowData), vendors ([VendorAllocation])
        worktype_vocab: List of valid worktypes for skill parsing (sorted longest-first)
        core_utils: CoreUtils instance

    Returns:
        Number of records inserted
    """
    logger.info(f"Populating FTE mappings from bench allocation for {month} {year}...")

    # Clear existing bench mappings
    clear_fte_mappings(month, year, 'bench', core_utils)

    if not consolidated_changes:
        logger.info("No consolidated changes to populate")
        return 0

    db_manager = core_utils.get_db_manager(
        FTEAllocationMappingModel,
        limit=None,
        skip=0,
        select_columns=None
    )

    records_to_insert = []

    for (forecast_id, month_index), change_data in consolidated_changes.items():
        forecast_row = change_data.get('forecast_row')
        vendors = change_data.get('vendors', [])

        if not forecast_row or not vendors:
            continue

        # Extract forecast details from ForecastRowData
        main_lob = forecast_row.main_lob
        state = forecast_row.state
        case_type = forecast_row.case_type
        call_type_id = forecast_row.call_type_id
        forecast_month = forecast_row.month_name
        forecast_year = forecast_row.month_year
        forecast_month_label = _get_month_label(forecast_month, forecast_year)

        # Process each vendor allocation
        for vendor in vendors:
            # Get raw NewWorkType from vendor.skills field
            new_work_type_raw = vendor.skills or ''

            # Parse skills - use vendor.skillset if available (already parsed), otherwise parse
            if vendor.skillset:
                skills_str = ', '.join(sorted(vendor.skillset))
            else:
                parsed_skills = parse_vendor_skills(new_work_type_raw, worktype_vocab)
                skills_str = ', '.join(sorted(parsed_skills)) if parsed_skills else ''

            record = FTEAllocationMappingModel(
                allocation_execution_id=execution_id,
                report_month=month,
                report_year=year,
                main_lob=main_lob,
                state=state,
                case_type=case_type,
                call_type_id=call_type_id or '',
                forecast_month=forecast_month,
                forecast_year=forecast_year,
                forecast_month_label=forecast_month_label,
                forecast_month_index=month_index,
                cn=vendor.cn,
                first_name=vendor.first_name or '',
                last_name=vendor.last_name or '',
                opid='',  # Not available in VendorAllocation
                primary_platform=vendor.platform or '',
                primary_market='',  # Not available in VendorAllocation
                location=vendor.location or '',
                original_state=vendor.original_state or '',
                worktype=new_work_type_raw,
                new_work_type=new_work_type_raw,
                skills=skills_str,
                allocation_type='bench'
            )
            records_to_insert.append(record)

    if not records_to_insert:
        logger.info("No FTE mapping records to insert")
        return 0

    try:
        with db_manager.SessionLocal() as session:
            session.add_all(records_to_insert)
            session.commit()

            logger.info(f"Inserted {len(records_to_insert)} FTE mapping records (bench)")
            return len(records_to_insert)

    except SQLAlchemyError as e:
        logger.error(f"Failed to insert FTE mappings: {e}", exc_info=True)
        return 0


def get_fte_mappings(
    report_month: str,
    report_year: int,
    main_lob: str,
    state: str,
    case_type: str,
    forecast_month_label: Optional[str] = None,
    core_utils: Any = None
) -> Dict[str, Any]:
    """
    Query FTE mappings for a specific forecast record.

    Args:
        report_month: Report month (e.g., "March")
        report_year: Report year (e.g., 2025)
        main_lob: Main LOB filter (e.g., "Amisys Medicaid Domestic")
        state: State filter (e.g., "LA", "N/A")
        case_type: Case type filter (e.g., "Claims Processing")
        forecast_month_label: Optional forecast month filter (e.g., "Apr-25")
        core_utils: CoreUtils instance (uses singleton if not provided)

    Returns:
        Dict with FTE mappings grouped by forecast month
    """
    if core_utils is None:
        core_utils = get_core_utils()

    db_manager = core_utils.get_db_manager(
        FTEAllocationMappingModel,
        limit=None,
        skip=0,
        select_columns=None
    )

    try:
        with db_manager.SessionLocal() as session:
            # Build query with case-insensitive matching
            query = session.query(FTEAllocationMappingModel).filter(
                and_(
                    FTEAllocationMappingModel.report_month == report_month,
                    FTEAllocationMappingModel.report_year == report_year,
                    FTEAllocationMappingModel.main_lob.ilike(main_lob),
                    FTEAllocationMappingModel.state.ilike(state),
                    FTEAllocationMappingModel.case_type.ilike(case_type)
                )
            )

            # Apply optional forecast month filter
            if forecast_month_label:
                query = query.filter(
                    FTEAllocationMappingModel.forecast_month_label == forecast_month_label
                )

            # Order by month label and CN
            query = query.order_by(
                FTEAllocationMappingModel.forecast_month_index,
                FTEAllocationMappingModel.cn
            )

            results = query.all()

            if not results:
                return {
                    'success': False,
                    'error': 'No FTE mappings found for the specified criteria',
                    'total_fte_count': 0,
                    'fte_by_month': {},
                    'forecast_months': []
                }

            # Group results by forecast month
            fte_by_month: Dict[str, Dict[str, Any]] = {}
            allocation_type_counts = {'primary': 0, 'bench': 0}
            execution_id = None

            for record in results:
                if execution_id is None:
                    execution_id = record.allocation_execution_id

                month_label = record.forecast_month_label
                if month_label not in fte_by_month:
                    fte_by_month[month_label] = {
                        'fte_count': 0,
                        'ftes': []
                    }

                fte_by_month[month_label]['fte_count'] += 1
                fte_by_month[month_label]['ftes'].append({
                    'cn': record.cn,
                    'first_name': record.first_name,
                    'last_name': record.last_name,
                    'opid': record.opid,
                    'primary_platform': record.primary_platform,
                    'primary_market': record.primary_market,
                    'location': record.location,
                    'original_state': record.original_state,
                    'worktype': record.worktype,
                    'new_work_type': record.new_work_type,
                    'skills': record.skills,
                    'allocation_type': record.allocation_type
                })

                allocation_type_counts[record.allocation_type] = \
                    allocation_type_counts.get(record.allocation_type, 0) + 1

            return {
                'success': True,
                'allocation_execution_id': execution_id,
                'total_fte_count': len(results),
                'allocation_type_summary': allocation_type_counts,
                'fte_by_month': fte_by_month,
                'forecast_months': sorted(fte_by_month.keys(), key=lambda x: (
                    # Sort by month index: Apr-25, May-25, Jun-25...
                    list(fte_by_month.keys()).index(x) if x in fte_by_month else 99
                ))
            }

    except SQLAlchemyError as e:
        logger.error(f"Failed to query FTE mappings: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'Database error: {str(e)}',
            'total_fte_count': 0,
            'fte_by_month': {},
            'forecast_months': []
        }
