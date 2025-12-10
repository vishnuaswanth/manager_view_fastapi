"""
Bench Resource Allocation Module

This module allocates unallocated (bench) vendors to forecast demands after
the initial allocation has been completed. It uses proportional distribution
with whole FTEs only, respecting state compatibility.

Key Features:
- Whole FTEs only (no decimals)
- State matching (vendor StateList must contain demand state)
- Fill gaps first, then distribute excess
- Proportional distribution using Largest Remainder Method
- Exports changes to Excel (Phase 1)
"""

from typing import List, Dict, Tuple, Optional
from datetime import datetime
from calendar import month_name as cal_month_name
import pandas as pd
import logging
import re

from code.logics.core_utils import CoreUtils
from code.logics.db import AllocationReportsModel, ForecastModel, MonthConfigurationModel
from code.logics.allocation import parse_main_lob, normalize_locality, Calculations
from code.logics.allocation_validity import validate_allocation_is_curre

logger = logging.getLogger(__name__)


def parse_vendor_state_list(state_str: str, valid_states: set) -> List[str]:
    """
    Parse vendor State column to create StateList.

    Follows the same logic as existing allocation system (allocation.py:453-534).
    Every vendor ALWAYS has 'N/A' in their StateList.

    Args:
        state_str: State string from vendor (e.g., "FL", "FL GA AR", "N/A", or empty)
        valid_states: Set of valid state codes from forecast demands

    Returns:
        List of states vendor can work in (always includes 'N/A')

    Examples:
        "FL" → ['FL', 'N/A']
        "FL GA AR" → ['FL', 'GA', 'N/A']
        "" → ['N/A']
    """
    state_str = str(state_str).strip().upper()

    if not state_str or state_str in {'NAN', 'NONE', ''}:
        return ['N/A']

    # Split by whitespace
    state_tokens = state_str.split()

    # US state pattern (2-letter codes)
    us_state_pattern = re.compile(r'^[A-Z]{2}$')

    # Specific demand states (excluding N/A)
    specific_demand_states = valid_states - {'N/A'}

    parsed_states = []
    for token in state_tokens:
        if us_state_pattern.match(token):
            # Valid 2-letter code
            if token in specific_demand_states:
                parsed_states.append(token)  # Matched state

    # Remove duplicates while preserving order
    seen = set()
    unique_states = []
    for s in parsed_states:
        if s not in seen:
            seen.add(s)
            unique_states.append(s)

    # ALWAYS add 'N/A' - every vendor can fulfill N/A demands
    if 'N/A' not in unique_states:
        unique_states.append('N/A')

    return unique_states


def get_unallocated_vendors_with_states(
    month: str,
    year: int,
    core_utils: CoreUtils
) -> Tuple[List[Dict], set]:
    """
    Get unallocated vendors from roster_allotment report with StateList parsing.

    Args:
        month: Month name (e.g., "January")
        year: Year (e.g., 2025)
        core_utils: CoreUtils instance for database access

    Returns:
        Tuple of (vendors_list, valid_states_set)
        - vendors_list: List of vendor dicts with state_list field
        - valid_states_set: Set of valid states from forecast data

    Raises:
        ValueError: If roster_allotment report not found
    """
    db_manager = core_utils.get_db_manager(AllocationReportsModel, limit=1, skip=0, select_columns=None)

    # Get latest roster_allotment report
    try:
        report_df = db_manager.get_latest_execution_report(month, year, 'roster_allotment')
        if report_df is None or report_df.empty:
            raise ValueError(f"No roster_allotment report found for {month} {year}")
    except Exception as e:
        raise ValueError(f"Error reading roster_allotment report: {e}")

    # Filter to unallocated vendors only
    unallocated_df = report_df[report_df['Status'] == 'Not Allocated'].copy()

    if unallocated_df.empty:
        logger.info(f"No unallocated vendors found for {month} {year}")
        return [], set()

    # Get valid states from forecast data for state parsing
    forecast_db = core_utils.get_db_manager(ForecastModel, limit=None, skip=0, select_columns=None)
    with forecast_db.SessionLocal() as session:
        forecast_records = session.query(ForecastModel).filter(
            ForecastModel.Month == month,
            ForecastModel.Year == year
        ).all()

        valid_states = {
            str(row.Centene_Capacity_Plan_State).strip().upper()
            for row in forecast_records
            if row.Centene_Capacity_Plan_State and
            str(row.Centene_Capacity_Plan_State).lower() not in {'nan', 'none', ''}
        }

    # Parse StateList for each vendor
    vendors = []
    for _, row in unallocated_df.iterrows():
        state_list = parse_vendor_state_list(row.get('State', ''), valid_states)

        vendor_dict = {
            'first_name': row.get('FirstName', ''),
            'last_name': row.get('LastName', ''),
            'cn': row.get('CN', ''),
            'platform': row.get('PrimaryPlatform', ''),
            'location': row.get('Location', ''),
            'skills': row.get('NewWorkType', ''),
            'state_list': state_list,
            'original_state': row.get('State', '')
        }
        vendors.append(vendor_dict)

    logger.info(f"Found {len(vendors)} unallocated vendors for {month} {year}")

    return vendors, valid_states


def unnormalize_forecast_data(
    month: str,
    year: int,
    core_utils: CoreUtils
) -> pd.DataFrame:
    """
    Read ForecastModel and unnormalize Month1-Month6 columns to separate rows.

    Each ForecastModel record has 6 months of data. This function creates
    one row per (LOB, State, Case_Type, Month) combination.

    Args:
        month: Month name (e.g., "January")
        year: Year (e.g., 2025)
        core_utils: CoreUtils instance for database access

    Returns:
        DataFrame with columns:
        - forecast_id: Original ForecastModel ID
        - main_lob: Main LOB
        - state: State
        - case_type: Case Type
        - target_cph: Target CPH
        - month_name: Actual month name
        - month_index: 1-6 (which MonthX column)
        - fte_required: FTE Required for this month
        - fte_avail: FTE Avail for this month
        - capacity: Capacity for this month

    Raises:
        ValueError: If no forecast data found
    """
    db_manager = core_utils.get_db_manager(ForecastModel, limit=None, skip=0, select_columns=None)

    with db_manager.SessionLocal() as session:
        forecast_records = session.query(ForecastModel).filter(
            ForecastModel.Month == month,
            ForecastModel.Year == year
        ).all()

        if not forecast_records:
            raise ValueError(f"No forecast data found for {month} {year}")

    # Unnormalize to month-level rows
    rows = []
    for record in forecast_records:
        for month_idx in range(1, 7):  # Month1 through Month6
            # Calculate actual month name for this index
            month_year_tuple = get_year_for_month(month, year, month_idx)
            actual_month_name = month_year_tuple['month']
            actual_year = month_year_tuple['year']

            row = {
                'forecast_id': record.id,
                'main_lob': record.Centene_Capacity_Plan_Main_LOB,
                'state': record.Centene_Capacity_Plan_State,
                'case_type': record.Centene_Capacity_Plan_Case_Type,
                'target_cph': record.Centene_Capacity_Plan_Target_CPH,
                'month_name': actual_month_name,
                'month_year': actual_year,
                'month_index': month_idx,
                'forecast': getattr(record, f'Client_Forecast_Month{month_idx}', 0) or 0,
                'fte_required': getattr(record, f'FTE_Required_Month{month_idx}', 0) or 0,
                'fte_avail': getattr(record, f'FTE_Avail_Month{month_idx}', 0) or 0,
                'fte_avail_original': getattr(record, f'FTE_Avail_Month{month_idx}', 0) or 0,
                'capacity': getattr(record, f'Capacity_Month{month_idx}', 0) or 0,
                'capacity_original': getattr(record, f'Capacity_Month{month_idx}', 0) or 0
            }
            rows.append(row)

    df = pd.DataFrame(rows)
    logger.info(f"Unnormalized forecast data: {len(df)} month-level rows from {len(forecast_records)} forecast records")

    return df


def get_year_for_month(data_month: str, data_year: int, month_index: int) -> Dict[str, any]:
    """
    Calculate the correct year for a month in a consecutive 6-month sequence.
    Handles year wrapping (e.g., Dec → Jan transitions).

    Reuses logic from allocation.py:92-127

    Args:
        data_month: Starting month name (e.g., "August")
        data_year: Starting year (e.g., 2024)
        month_index: Index 1-6 for MonthX

    Returns:
        Dict with 'month' (name) and 'year'

    Examples:
        get_year_for_month("August", 2024, 1) → {month: "August", year: 2024}
        get_year_for_month("August", 2024, 6) → {month: "January", year: 2025}
    """
    month_names = list(cal_month_name)[1:]  # Skip empty string at index 0

    # Get starting month number (1-12)
    try:
        start_month_num = month_names.index(data_month) + 1
    except ValueError:
        raise ValueError(f"Invalid month name: {data_month}")

    # Calculate target month number
    target_month_num = start_month_num + (month_index - 1)

    # Handle year wrapping
    target_year = data_year
    while target_month_num > 12:
        target_month_num -= 12
        target_year += 1

    target_month_name = month_names[target_month_num - 1]

    return {
        'month': target_month_name,
        'year': target_year
    }


def normalize_platform(main_lob: str) -> str:
    """
    Normalize platform from Main LOB.

    Reuses parse_main_lob from allocation.py and extracts first word.
    """
    parsed = parse_main_lob(main_lob)
    platform = parsed.get('platform', '')
    # Extract first word and uppercase
    if platform:
        return platform.strip().split()[0].upper()
    return ''


def normalize_worktype(case_type: str) -> str:
    """Normalize worktype to lowercase for matching."""
    if not case_type or str(case_type).lower() in {'nan', 'none', ''}:
        return ''
    return str(case_type).strip().lower()


def group_into_buckets(
    vendors: List[Dict],
    forecast_df: pd.DataFrame,
    worktype_vocab: set
) -> Dict[Tuple, Dict]:
    """
    Group vendors and forecast rows into buckets by (Platform, Location, Month, Skillset).

    Args:
        vendors: List of unallocated vendor dicts
        forecast_df: Unnormalized forecast DataFrame
        worktype_vocab: Set of valid worktypes from forecast data

    Returns:
        Dict mapping bucket_key to {vendors: [...], forecast_rows: [...]}
        where bucket_key = (platform, location, month, skillset)
    """
    buckets = {}

    # Parse vendor skills and group
    for vendor in vendors:
        # Normalize platform
        platform_norm = vendor['platform'].strip().split()[0].upper() if vendor['platform'] else ''

        # Normalize location
        location_norm = normalize_locality(vendor['location'])

        # Parse skills (simplified - match against vocab)
        skills_text = normalize_worktype(vendor['skills'])
        matched_skills = set()
        for vocab_term in worktype_vocab:
            if vocab_term in skills_text:
                matched_skills.add(vocab_term)

        if not matched_skills:
            continue  # Skip vendors with no recognized skills

        skillset = frozenset(matched_skills)

        # Vendor can work in multiple months - get from StateList months
        # For now, we'll add to buckets when matching forecast rows
        vendor['platform_norm'] = platform_norm
        vendor['location_norm'] = location_norm
        vendor['skillset'] = skillset

    # Group forecast rows and match vendors
    for _, row in forecast_df.iterrows():
        platform_norm = normalize_platform(row['main_lob'])
        location_norm = normalize_locality(parse_main_lob(row['main_lob'])['locality'])
        month_name = row['month_name']
        worktype_norm = normalize_worktype(row['case_type'])

        if not worktype_norm:
            continue

        # Find vendors with matching skills
        matching_vendors = []
        for vendor in vendors:
            if (vendor.get('platform_norm') == platform_norm and
                vendor.get('location_norm') == location_norm and
                worktype_norm in vendor.get('skillset', set())):
                matching_vendors.append(vendor)

        if not matching_vendors:
            continue  # No vendors for this forecast row

        # Create bucket key
        skillset = frozenset([worktype_norm])  # Forecast row has single worktype
        bucket_key = (platform_norm, location_norm, month_name, skillset)

        if bucket_key not in buckets:
            buckets[bucket_key] = {
                'vendors': [],
                'forecast_rows': []
            }

        # Add forecast row
        buckets[bucket_key]['forecast_rows'].append(row.to_dict())

        # Add vendors (avoid duplicates)
        for vendor in matching_vendors:
            if vendor not in buckets[bucket_key]['vendors']:
                buckets[bucket_key]['vendors'].append(vendor)

    logger.info(f"Created {len(buckets)} buckets")
    return buckets


def fill_gaps(
    bucket_data: Dict,
    bucket_key: Tuple
) -> List[Dict]:
    """
    Fill gaps (FTE_Avail < FTE_Required) with state-compatible vendors.

    Args:
        bucket_data: Dict with 'vendors' and 'forecast_rows' lists
        bucket_key: (platform, location, month, skillset)

    Returns:
        List of allocation dicts: [{forecast_row, vendor, fte_allocated, type}]
    """
    allocations = []
    vendors = bucket_data['vendors'].copy()  # Work with copy
    forecast_rows = bucket_data['forecast_rows']

    # Find rows with gaps
    gap_rows = [row for row in forecast_rows if row['fte_avail'] < row['fte_required']]

    for row in gap_rows:
        gap = int(row['fte_required'] - row['fte_avail'])
        if gap <= 0:
            continue

        demand_state = str(row['state']).strip().upper()

        # Allocate vendors one-by-one to fill gap
        for _ in range(gap):
            # Find compatible vendor (state match)
            compatible_vendor = None
            for vendor in vendors:
                if demand_state in vendor['state_list']:
                    compatible_vendor = vendor
                    break

            if compatible_vendor:
                # Allocate this vendor
                allocations.append({
                    'forecast_row': row,
                    'vendor': compatible_vendor,
                    'fte_allocated': 1,
                    'allocation_type': 'gap_fill'
                })

                # Update row's FTE_Avail
                row['fte_avail'] += 1

                # Remove vendor from available list
                vendors.remove(compatible_vendor)
            else:
                # No compatible vendors left for this state
                logger.warning(f"Could not fill gap for {row['main_lob']} {row['state']} {row['month_name']} - no state-compatible vendors")
                break

    # Update bucket data with remaining vendors
    bucket_data['vendors'] = vendors

    logger.info(f"Filled {len(allocations)} gaps for bucket {bucket_key}")
    return allocations


def distribute_proportionally(
    bucket_data: Dict,
    bucket_key: Tuple
) -> List[Dict]:
    """
    Distribute remaining bench vendors proportionally using Largest Remainder Method.

    Args:
        bucket_data: Dict with 'vendors' and 'forecast_rows' lists
        bucket_key: (platform, location, month, skillset)

    Returns:
        List of allocation dicts: [{forecast_row, vendor, fte_allocated, type}]
    """
    allocations = []
    vendors = bucket_data['vendors']  # Already updated by fill_gaps
    forecast_rows = bucket_data['forecast_rows']

    if not vendors:
        logger.info(f"No remaining vendors for bucket {bucket_key}")
        return allocations

    num_vendors = len(vendors)

    # Calculate total demand
    total_demand = sum(row['forecast'] for row in forecast_rows)
    if total_demand == 0:
        logger.warning(f"Total forecast volume is zero for bucket {bucket_key}")
        return allocations

    # Calculate ideal shares
    ideal_shares = [
        num_vendors * (row['forecast'] / total_demand)
        for row in forecast_rows
    ]

    # Floor allocation
    floor_allocations = [int(share) for share in ideal_shares]
    allocated_count = sum(floor_allocations)

    # Largest Remainder Method for remaining
    remainders = [ideal - floor for ideal, floor in zip(ideal_shares, floor_allocations)]
    remaining = num_vendors - allocated_count

    # Sort by remainder (descending) and allocate
    if remaining > 0:
        indexed_remainders = list(enumerate(remainders))
        indexed_remainders.sort(key=lambda x: x[1], reverse=True)

        for i in range(min(remaining, len(indexed_remainders))):
            row_idx = indexed_remainders[i][0]
            floor_allocations[row_idx] += 1

    # Allocate vendors to rows based on final allocation counts
    vendor_idx = 0
    for row_idx, allocation_count in enumerate(floor_allocations):
        if allocation_count == 0:
            continue

        row = forecast_rows[row_idx]
        demand_state = str(row['state']).strip().upper()

        # Allocate 'allocation_count' vendors to this row
        for _ in range(allocation_count):
            if vendor_idx >= len(vendors):
                logger.warning(f"Ran out of vendors during proportional distribution")
                break

            # Find next compatible vendor
            compatible_vendor = None
            search_start = vendor_idx
            while vendor_idx < len(vendors):
                vendor = vendors[vendor_idx]
                if demand_state in vendor['state_list']:
                    compatible_vendor = vendor
                    break
                vendor_idx += 1

            if not compatible_vendor:
                # No compatible vendor found, reset search and try N/A match
                vendor_idx = search_start
                while vendor_idx < len(vendors):
                    vendor = vendors[vendor_idx]
                    if 'N/A' in vendor['state_list']:  # All vendors have N/A
                        compatible_vendor = vendor
                        break
                    vendor_idx += 1

            if compatible_vendor:
                allocations.append({
                    'forecast_row': row,
                    'vendor': compatible_vendor,
                    'fte_allocated': 1,
                    'allocation_type': 'excess_distribution'
                })

                # Update row's FTE_Avail
                row['fte_avail'] += 1

                vendor_idx += 1
            else:
                logger.warning(f"Could not allocate vendor to {row['main_lob']} {row['state']} {row['month_name']}")

    logger.info(f"Distributed {len(allocations)} excess vendors for bucket {bucket_key}")
    return allocations


def allocate_bench_for_month(
    month: str,
    year: int,
    core_utils: CoreUtils
) -> Dict:
    """
    Main orchestration function for bench allocation.

    Args:
        month: Month name (e.g., "January")
        year: Year (e.g., 2025)
        core_utils: CoreUtils instance for database access

    Returns:
        Dict with results:
        - success: bool
        - month: str
        - year: int
        - total_bench_allocated: int
        - gaps_filled: int
        - excess_distributed: int
        - rows_modified: int
        - allocations: List[Dict]
        - error: str (if failed)
    """
    try:
        logger.info(f"=== Starting bench allocation for {month} {year} ===")

        # Step 1: Validate allocation is current
        validity_check = validate_allocation_is_current(month, year, core_utils)
        if not validity_check['valid']:
            logger.error(f"Allocation validation failed: {validity_check.get('error')}")
            return {
                'success': False,
                'error': validity_check.get('error'),
                'recommendation': validity_check.get('recommendation')
            }

        logger.info(f"✓ Allocation is valid (execution: {validity_check['execution_id']})")

        # Step 2: Get unallocated vendors
        vendors, valid_states = get_unallocated_vendors_with_states(month, year, core_utils)
        if not vendors:
            logger.info("No unallocated vendors found")
            return {
                'success': True,
                'month': month,
                'year': year,
                'total_bench_allocated': 0,
                'gaps_filled': 0,
                'excess_distributed': 0,
                'rows_modified': 0,
                'allocations': [],
                'message': 'No bench vendors available for allocation'
            }

        logger.info(f"✓ Found {len(vendors)} unallocated vendors")

        # Initialize calculations for capacity updates
        calculations = Calculations(data_month=month, data_year=year)

        # Step 3: Unnormalize forecast data
        forecast_df = unnormalize_forecast_data(month, year, core_utils)
        logger.info(f"✓ Loaded {len(forecast_df)} forecast rows")

        # Build worktype vocabulary
        worktype_vocab = set(forecast_df['case_type'].apply(normalize_worktype).unique())
        worktype_vocab.discard('')

        # Step 4: Group into buckets
        buckets = group_into_buckets(vendors, forecast_df, worktype_vocab)
        logger.info(f"✓ Created {len(buckets)} buckets")

        # Step 5: Allocate per bucket
        all_allocations = []
        for bucket_key, bucket_data in buckets.items():
            logger.info(f"\nProcessing bucket: {bucket_key}")
            logger.info(f"  Vendors: {len(bucket_data['vendors'])}, Forecast rows: {len(bucket_data['forecast_rows'])}")

            # Fill gaps first
            gap_allocations = fill_gaps(bucket_data, bucket_key)
            all_allocations.extend(gap_allocations)

            # Distribute excess
            excess_allocations = distribute_proportionally(bucket_data, bucket_key)
            all_allocations.extend(excess_allocations)

        # Step 6: Calculate summary and consolidate allocations
        gaps_filled = len([a for a in all_allocations if a['allocation_type'] == 'gap_fill'])
        excess_distributed = len([a for a in all_allocations if a['allocation_type'] == 'excess_distribution'])

        # Consolidate allocations by forecast_id
        consolidated_allocations = {}
        for allocation in all_allocations:
            f_id = allocation['forecast_row']['forecast_id']

            if f_id not in consolidated_allocations:
                # Initialize with the row state (which is updated in-place during allocation)
                consolidated_allocations[f_id] = {
                    'forecast_row': allocation['forecast_row'],
                    'vendors': [],
                    'gap_fill_count': 0,
                    'excess_distribution_count': 0,
                    'fte_change': 0,
                    'capacity_change': 0
                }

            # Add vendor details
            consolidated_allocations[f_id]['vendors'].append(allocation['vendor'])

            # Update counts
            if allocation['allocation_type'] == 'gap_fill':
                consolidated_allocations[f_id]['gap_fill_count'] += 1
            elif allocation['allocation_type'] == 'excess_distribution':
                consolidated_allocations[f_id]['excess_distribution_count'] += 1

            # Update total change
            consolidated_allocations[f_id]['fte_change'] += allocation['fte_allocated']

        # Recalculate capacity for consolidated rows
        for f_id, data in consolidated_allocations.items():
            row = data['forecast_row']

            # Determine work type (Domestic/Global)
            main_lob = row['main_lob']
            case_type = row['case_type']
            parsed_lob = parse_main_lob(main_lob)
            lob_locality = parsed_lob.get('locality', '')

            # SPECIAL CASE: OIC Volumes
            is_oic_volumes = 'oic' in str(main_lob).lower() and 'volumes' in str(main_lob).lower()
            if is_oic_volumes:
                case_type_lower = str(case_type).lower()
                work_type = 'Domestic' if 'domestic' in case_type_lower else 'Global'
            else:
                work_type = 'Domestic' if 'domestic' in str(lob_locality).lower() else 'Global'

            # Get config for this specific row's month/year
            try:
                config = calculations.get_config_for_worktype(row['month_name'], row['month_year'], work_type)

                # Calculate new capacity
                new_capacity = (
                    row['target_cph'] *
                    row['fte_avail'] *
                    (1 - config['shrinkage']) *
                    config['working_days'] *
                    config['work_hours']
                )

                old_capacity = row.get('capacity_original', row['capacity'])
                row['capacity'] = int(round(new_capacity))
                data['capacity_change'] = row['capacity'] - old_capacity

            except Exception as e:
                logger.warning(f"Could not recalculate capacity for forecast_id {f_id}: {e}")

        final_allocations_list = list(consolidated_allocations.values())

        logger.info(f"\n=== Allocation Complete ===")
        logger.info(f"Total allocated: {len(all_allocations)}")
        logger.info(f"Gaps filled: {gaps_filled}")
        logger.info(f"Excess distributed: {excess_distributed}")
        logger.info(f"Rows modified: {len(consolidated_allocations)}")

        return {
            'success': True,
            'month': month,
            'year': year,
            'total_bench_allocated': len(all_allocations),
            'gaps_filled': gaps_filled,
            'excess_distributed': excess_distributed,
            'rows_modified': len(consolidated_allocations),
            'allocations': final_allocations_list
        }

    except Exception as e:
        logger.error(f"Error during bench allocation: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }

