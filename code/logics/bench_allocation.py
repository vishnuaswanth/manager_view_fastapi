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
from dataclasses import dataclass, field
import pandas as pd
import logging
import re

from code.logics.core_utils import CoreUtils
from code.logics.db import AllocationReportsModel, ForecastModel, MonthConfigurationModel
from code.logics.allocation import parse_main_lob, normalize_locality, Calculations
from code.logics.allocation_validity import validate_allocation_is_current
from code.logics.month_config_utils import get_specific_config
from sqlmodel import select, and_

logger = logging.getLogger(__name__)


# ============================================================================
# TYPE-SAFE DATA STRUCTURES
# ============================================================================

@dataclass
class VendorAllocation:
    """Single vendor allocation details"""
    first_name: str
    last_name: str
    cn: str
    platform: str
    location: str
    skills: str
    state_list: List[str]
    original_state: str
    allocated: bool
    part_of_production: str = ''  # Default empty string for backward compatibility


@dataclass
class ForecastRowData:
    """Forecast row data with allocation updates"""
    forecast_id: int
    main_lob: str
    state: str
    case_type: str
    target_cph: int
    month_name: str
    month_year: int
    month_index: int
    forecast: float
    fte_required: int
    fte_avail: int
    fte_avail_original: int
    capacity: int
    capacity_original: int


@dataclass
class AllocationRecord:
    """Single allocation record with forecast and vendor details"""
    forecast_row: ForecastRowData
    vendors: List[VendorAllocation]
    gap_fill_count: int
    excess_distribution_count: int
    fte_change: int
    capacity_change: int


@dataclass
class AllocationResult:
    """Complete allocation result with type safety"""
    success: bool
    month: str
    year: int
    total_bench_allocated: int
    gaps_filled: int
    excess_distributed: int
    rows_modified: int
    allocations: List[AllocationRecord]
    error: str = ""  # Only populated if success=False


# ============================================================================
# NEW DATACLASS STRUCTURES (REPLACING TYPEDDICT)
# ============================================================================

@dataclass(frozen=True)
class MonthData:
    """Month mapping data (immutable)"""
    month: str
    year: int


@dataclass
class VendorData:
    """Vendor data with normalization fields"""
    first_name: str
    last_name: str
    cn: str
    platform: str
    location: str
    skills: str
    state_list: List[str]
    original_state: str
    allocated: bool
    part_of_production: str = ''  # Part of production indicator for future scenarios
    # Normalized fields (added during bucketing)
    platform_norm: Optional[str] = None
    location_norm: Optional[str] = None
    skillset: Optional[frozenset[str]] = None

    def __hash__(self):
        return hash(self.cn)

    def __eq__(self, other):
        if not isinstance(other, VendorData):
            return False
        return self.cn == other.cn


@dataclass
class ForecastRowDict:
    """Mutable forecast row data used during allocation processing"""
    forecast_id: int
    main_lob: str
    state: str
    case_type: str
    target_cph: int
    month_name: str
    month_year: int
    month_index: int
    forecast: float
    fte_required: int
    fte_avail: int
    fte_avail_original: int
    capacity: int
    capacity_original: int

    # Pre-parsed normalized fields (parsed once during normalization to avoid redundant parse_main_lob calls)
    platform_norm: str = ''    # Normalized platform: "AMISYS", "FACETS", etc.
    locality_norm: str = ''    # Normalized locality: "Domestic", "Global"
    market: str = ''           # Market/LOB name: "Medicaid", "Medicare", "OIC Volumes", etc.


@dataclass(frozen=True)
class AllocationData:
    """Single allocation record (immutable)"""
    forecast_row: ForecastRowDict
    vendor: VendorData
    fte_allocated: int
    allocation_type: str  # 'gap_fill' or 'excess_distribution'


@dataclass
class BucketData:
    """Bucket data structure (mutable for algorithm efficiency)"""
    vendors: List[VendorData]
    forecast_rows: List[ForecastRowDict]


# ============================================================================
# TYPE ALIASES
# ============================================================================

# Type alias for bucket keys: (platform, location, month, state_set, skillset)
BucketKey = Tuple[str, str, str, frozenset[str], frozenset[str]]


def parse_vendor_state_list(state_str: str, valid_states: set) -> List[str]:
    """
    Parse vendor State column to create StateList.

    CRITICAL CHANGE FOR BENCH ALLOCATION: Does NOT automatically add 'N/A'.
    This enables two-cycle state matching:
    - Cycle 1: Try specific states (FL, GA, TX)
    - Cycle 2: Fall back to N/A if no specific matches

    Args:
        state_str: State string from vendor (e.g., "FL", "FL GA AR", "N/A", or empty)
        valid_states: Set of valid state codes from forecast demands

    Returns:
        List of specific states vendor can work in (NO automatic 'N/A')

    Examples:
        "FL" → ['FL']  (NOT ['FL', 'N/A'] like primary allocation)
        "FL GA AR" → ['FL', 'GA']
        "" → ['N/A']  (empty state defaults to N/A only)
        "N/A" → ['N/A']
    """
    state_str = str(state_str).strip().upper()

    if not state_str or state_str in {'NAN', 'NONE', ''}:
        return ['N/A']  # Empty state → N/A only

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

    # If no specific states parsed, default to N/A
    if not unique_states:
        return ['N/A']

    # DO NOT automatically add 'N/A' - bench allocation uses two-cycle matching
    # N/A fallback is handled in bucket initialization
    return unique_states


def get_unallocated_vendors_with_states(
    execution_id: str,
    month: str,
    year: int,
    core_utils: CoreUtils
) -> Tuple[List[VendorData], set[str]]:
    """
    Get unallocated vendors from roster_allotment report with StateList parsing.

    Args:
        execution_id: The execution UUID from AllocationExecutionModel
        month: Month name (e.g., "January") - for fallback/validation
        year: Year (e.g., 2025) - for fallback/validation
        core_utils: CoreUtils instance for database access

    Returns:
        Tuple of (vendors_list, valid_states_set)
        - vendors_list: List of VendorData dataclass instances with state_list field
        - valid_states_set: Set of valid states from forecast data

    Raises:
        ValueError: If roster_allotment report not found
    """
    import json

    db_manager = core_utils.get_db_manager(AllocationReportsModel, limit=None, skip=0, select_columns=None)

    # Get roster_allotment report using execution_id
    try:
        with db_manager.SessionLocal() as session:
            report = session.query(AllocationReportsModel).filter(
                AllocationReportsModel.execution_id == execution_id,
                AllocationReportsModel.ReportType == 'roster_allotment'
            ).first()

            if not report:
                raise ValueError(f"No roster_allotment report found for execution_id: {execution_id}")

            # Parse JSON report data to DataFrame
            report_data = json.loads(report.ReportData)
            report_df = pd.DataFrame(report_data)

            if report_df.empty:
                raise ValueError(f"Empty roster_allotment report for execution_id: {execution_id}")

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

        vendor = VendorData(
            first_name=row.get('FirstName', ''),
            last_name=row.get('LastName', ''),
            cn=row.get('CN', ''),
            platform=row.get('PrimaryPlatform', ''),
            location=row.get('Location', ''),
            skills=row.get('NewWorkType', ''),
            state_list=state_list,
            original_state=row.get('State', ''),
            allocated=False,
            part_of_production=row.get('PartOfProduction', '')  # Read from roster data
        )
        vendors.append(vendor)

    logger.info(f"Found {len(vendors)} unallocated vendors for {month} {year}")

    return vendors, valid_states


def get_month_mappings_from_db(
    core_utils: CoreUtils,
    uploaded_file: str,
    report_month: str,
    report_year: int
) -> Dict[int, MonthData]:
    """
    Get month mappings from ForecastMonthsModel with correct year calculation.

    ForecastMonthsModel only contains month names (Month1-Month6), not years.
    We calculate the year based on the report month using this logic:
    - If report_month_num > forecast_month_num → year = report_year + 1 (wrapped to next year)
    - Otherwise → year = report_year (same year)

    Example 1 (March 2025 Report):
        Month1 = April: 3 > 4? No → 2025
        Month2 = May: 3 > 5? No → 2025
        ...all months are 2025 (no wrapping)

    Example 2 (October 2024 Report):
        Month1 = November: 10 > 11? No → 2024
        Month2 = December: 10 > 12? No → 2024
        Month3 = January: 10 > 1? Yes → 2025 (wrapped!)
        Month4 = February: 10 > 2? Yes → 2025
        ...

    CRITICAL: This function also validates that month configurations exist for
    both Domestic and Global localities. If ANY config is missing, the entire
    process stops with an error.

    Args:
        core_utils: CoreUtils instance for database access
        uploaded_file: The UploadedFile name from ForecastModel
        report_month: Report month name (e.g., "March")
        report_year: Report year (e.g., 2025)

    Returns:
        Dict mapping month_index (1-6) to MonthData(month=name, year=year)

    Raises:
        ValueError: If no month mappings found or month config missing
    """
    from code.logics.db import ForecastMonthsModel
    from code.logics.month_config_utils import get_specific_config

    db_manager = core_utils.get_db_manager(ForecastMonthsModel, limit=1, skip=0)

    with db_manager.SessionLocal() as session:
        months_record = session.query(ForecastMonthsModel).filter(
            ForecastMonthsModel.UploadedFile == uploaded_file
        ).first()

        if not months_record:
            raise ValueError(f"No month mappings found for file: {uploaded_file}")

    # Create mapping from month name to month number (1-12)
    month_names = list(cal_month_name)[1:]  # ['January', 'February', ..., 'December']
    month_to_num = {month: idx for idx, month in enumerate(month_names, start=1)}

    # Get report month number
    report_month_num = month_to_num.get(report_month)
    if report_month_num is None:
        raise ValueError(f"Invalid report month: {report_month}")

    # Build mappings from DB data with year calculation
    mappings = {}
    missing_configs = []

    for i in range(1, 7):
        month_name = getattr(months_record, f'Month{i}')

        if month_name not in month_to_num:
            raise ValueError(f"Invalid month name in ForecastMonthsModel.Month{i}: {month_name}")

        forecast_month_num = month_to_num[month_name]

        # CRITICAL: Year wrapping logic
        # If report_month_num > forecast_month_num → wrapped to next year
        if report_month_num > forecast_month_num:
            year = report_year + 1
        else:
            year = report_year

        mappings[i] = MonthData(month=month_name, year=year)

        logger.debug(
            f"Month{i} → {month_name} {year} "
            f"(report: {report_month} {report_year}, "
            f"month_nums: {report_month_num} vs {forecast_month_num})"
        )

        # CRITICAL: Validate month config exists for both Domestic and Global
        # If config missing, collect error but continue to check all months
        try:
            for locality in ['Domestic', 'Global']:
                config = get_specific_config(month_name, year, locality)
                if not config:
                    missing_configs.append(f"{month_name} {year} ({locality})")
        except Exception as e:
            missing_configs.append(f"{month_name} {year}: {str(e)}")

    # If any month configs are missing, STOP the entire process
    if missing_configs:
        error_msg = (
            f"Month configuration missing for forecast months. "
            f"Cannot proceed with bench allocation.\n"
            f"Missing configs: {', '.join(missing_configs)}"
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    logger.info(f"✓ All month configurations validated for {report_month} {report_year}")
    return mappings


def _dataframe_row_to_forecast_dict(row: pd.Series) -> ForecastRowDict:
    """
    Convert DataFrame row to ForecastRowDict dataclass.

    Args:
        row: pandas Series with columns:
            - forecast_id: int - Original ForecastModel record ID
            - main_lob: str - Main Line of Business
            - state: str - State code (e.g., 'FL', 'N/A')
            - case_type: str - Case type/worktype
            - target_cph: int - Target cases per hour
            - month_name: str - Month name (e.g., 'January')
            - month_year: int - Year for this month
            - month_index: int - Month position (1-6)
            - forecast: float - Client forecast volume
            - fte_required: int - FTE required for forecast
            - fte_avail: int - FTE available (updated during allocation)
            - fte_avail_original: int - Original FTE available
            - capacity: int - Calculated capacity (updated during allocation)
            - capacity_original: int - Original capacity
            - platform_norm: str - Pre-parsed platform ("AMISYS", "FACETS")
            - locality_norm: str - Pre-parsed locality ("Domestic", "Global")
            - market: str - Pre-parsed market/LOB name

    Returns:
        ForecastRowDict dataclass instance
    """
    return ForecastRowDict(
        forecast_id=row['forecast_id'],
        main_lob=row['main_lob'],
        state=row['state'],
        case_type=row['case_type'],
        target_cph=row['target_cph'],
        month_name=row['month_name'],
        month_year=row['month_year'],
        month_index=row['month_index'],
        forecast=row['forecast'],
        fte_required=row['fte_required'],
        fte_avail=row['fte_avail'],
        fte_avail_original=row['fte_avail_original'],
        capacity=row['capacity'],
        capacity_original=row['capacity_original'],
        # Pre-parsed normalized fields
        platform_norm=row['platform_norm'],
        locality_norm=row['locality_norm'],
        market=row['market']
    )


def normalize_forecast_data(
    month: str,
    year: int,
    core_utils: CoreUtils
) -> pd.DataFrame:
    """
    Read ForecastModel and normalize Month1-Month6 columns to separate rows.

    Each ForecastModel record has 6 months of data in wide format (denormalized).
    This function normalizes it to long format: one row per (LOB, State, Case_Type, Month) combination.

    Uses ForecastMonthsModel to get actual month names (future-proof).

    Args:
        month: Month name (e.g., "January")
        year: Year (e.g., 2025)
        core_utils: CoreUtils instance for database access

    Returns:
        DataFrame with columns (can be converted to ForecastRowDict using _dataframe_row_to_forecast_dict):
        - forecast_id: int - Original ForecastModel record ID
        - main_lob: str - Main Line of Business (e.g., "Medicaid IL - Domestic")
        - state: str - State code (e.g., "FL", "N/A")
        - case_type: str - Case type/worktype (e.g., "appeals", "grievances")
        - target_cph: int - Target cases per hour
        - month_name: str - Actual month name (e.g., "January")
        - month_year: int - Year for this specific month (handles year wrapping)
        - month_index: int - Month position 1-6 (which MonthX column this came from)
        - forecast: float - Client forecast volume for this month
        - fte_required: int - FTE required to meet forecast demand
        - fte_avail: int - FTE available (will be updated during allocation)
        - fte_avail_original: int - Original FTE available before allocation
        - capacity: int - Calculated capacity (will be updated during allocation)
        - capacity_original: int - Original capacity before allocation

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

    # Get month mappings from ForecastMonthsModel (future-proof!)
    if forecast_records:
        uploaded_file = forecast_records[0].UploadedFile
        month_mappings = get_month_mappings_from_db(core_utils, uploaded_file, month, year)
        logger.debug(f"Using ForecastMonthsModel month mappings for file: {uploaded_file}")
    else:
        raise ValueError(f"No forecast records found for {month} {year}")

    # Unnormalize to month-level rows
    rows = []
    for record in forecast_records:
        # Parse common fields ONCE per record (outside month loop for 6x performance gain)
        forecast_id = record.id
        main_lob = record.Centene_Capacity_Plan_Main_LOB
        state = record.Centene_Capacity_Plan_State
        case_type = record.Centene_Capacity_Plan_Case_Type
        target_cph = record.Centene_Capacity_Plan_Target_CPH

        # Parse main_lob ONCE per record (not 6 times per month)
        parsed = parse_main_lob(main_lob)

        # Extract normalized fields ONCE
        platform_raw = parsed.get('platform', '')
        platform_norm = platform_raw.strip().split()[0].upper() if platform_raw else ''
        locality_norm = normalize_locality(parsed.get('locality', ''))
        market = parsed.get('market', '')

        # Loop only for month-specific fields (6 iterations per record)
        for month_idx in range(1, 7):  # Month1 through Month6
            # Get actual month name and year from DB mappings
            month_data = month_mappings[month_idx]
            actual_month_name = month_data.month
            actual_year = month_data.year

            row = {
                # Common fields (reused from variables above - no redundant parsing)
                'forecast_id': forecast_id,
                'main_lob': main_lob,
                'state': state,
                'case_type': case_type,
                'target_cph': target_cph,
                'platform_norm': platform_norm,
                'locality_norm': locality_norm,
                'market': market,

                # Month-specific fields (vary per month)
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


def get_year_for_month(data_month: str, data_year: int, month_index: int) -> MonthData:
    """
    Calculate the correct year for a month in a consecutive 6-month sequence.
    Handles year wrapping (e.g., Dec → Jan transitions).

    Reuses logic from allocation.py:92-127

    Args:
        data_month: Starting month name (e.g., "August")
        data_year: Starting year (e.g., 2024)
        month_index: Index 1-6 for MonthX

    Returns:
        MonthData with month (name) and year

    Examples:
        get_year_for_month("August", 2024, 1) → MonthData(month="August", year=2024)
        get_year_for_month("August", 2024, 6) → MonthData(month="January", year=2025)
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

    return MonthData(
        month=target_month_name,
        year=target_year
    )


def normalize_worktype(case_type: str) -> str:
    """Normalize worktype to lowercase for matching."""
    if not case_type or str(case_type).lower() in {'nan', 'none', ''}:
        return ''
    return str(case_type).strip().lower()


def normalize_text(text: str) -> str:
    """
    Normalize whitespace: collapse multiple spaces/tabs to single space, strip.

    Example: "FTC  ADJ" → "FTC ADJ"
    """
    if not text or str(text).lower() == 'nan':
        return ''
    # Collapse multiple whitespace characters to single space
    return re.sub(r'\s+', ' ', str(text).strip())


def build_worktype_vocabulary(forecast_df: pd.DataFrame) -> List[str]:
    """
    Extract unique worktypes from forecast DataFrame, sorted by length (longest first).

    Critical: Longest strings MUST be checked first to avoid substring matching issues.
    Example: "FTC-Basic/Non MMP" must be checked before "FTC" or "FTC Basic"

    Args:
        forecast_df: Normalized forecast DataFrame with 'case_type' column

    Returns:
        List of worktypes sorted by length (descending), then alphabetically
    """
    worktypes = forecast_df['case_type'].unique()

    # Clean and filter vocabulary
    vocab = {
        str(wt).strip().lower()
        for wt in worktypes
        if wt and str(wt).lower() not in {'nan', 'none', ''}
    }

    # Sort by length DESC (longest first), then alphabetically for deterministic behavior
    return sorted(vocab, key=lambda x: (-len(x), x))


def parse_vendor_skills(newworktype_str: str, worktype_vocab: List[str]) -> frozenset:
    """
    Parse vendor NewWorkType by matching against vocabulary using greedy longest-match-first.

    Algorithm:
    1. Normalize whitespace and lowercase
    2. Find longest vocabulary term in remaining text
    3. Add to matched_skills, remove from text, re-normalize
    4. Repeat until no matches found

    Duplicates are automatically handled via set - if the same skill appears multiple times,
    it will only be included once in the result.

    Examples:
        Input: "FTC-Basic/Non MMP  ADJ-COB NON MMP" (note double space)
        Vocab: ["ftc-basic/non mmp", "adj-cob non mmp", "ftc", "adj", ...]
        Output: frozenset({'ftc-basic/non mmp', 'adj-cob non mmp'})

        Input: "FTC ADJ FTC" (duplicate FTC)
        Output: frozenset({'ftc', 'adj'})  # Deduplicates automatically

    Args:
        newworktype_str: Vendor's NewWorkType field
        worktype_vocab: List of valid worktypes sorted longest-first

    Returns:
        Frozenset of matched worktypes
    """
    if not newworktype_str:
        return frozenset()

    # Step 1: Normalize and lowercase
    text = normalize_text(newworktype_str).lower()

    # Step 2: Greedy matching
    matched_skills = set()  # Use set for automatic deduplication

    while text:
        matched_any = False

        # Check each vocab term (already sorted longest-first)
        for vocab_term in worktype_vocab:
            if vocab_term in text:
                matched_skills.add(vocab_term)  # Add to set (deduplicates automatically)
                # Remove matched term and re-normalize
                text = text.replace(vocab_term, ' ', 1)
                text = normalize_text(text)
                matched_any = True
                break  # Start over from beginning of vocab (longest-first)

        if not matched_any:
            # No more vocabulary matches, stop
            # (remaining text contains only unknown/non-demand skills)
            break

    return frozenset(matched_skills)


def group_into_buckets(
    vendors: List[VendorData],
    forecast_df: pd.DataFrame,
    worktype_vocab: List[str]
) -> Dict[BucketKey, BucketData]:
    """
    Group vendors and forecast rows into buckets by (Platform, Location, Month, Skillset).

    IMPORTANT: Uses greedy longest-match-first algorithm to parse vendor skills.
    This prevents "FTC-Basic/Non MMP" from being split into ["ftc-basic/non mmp", "ftc"].

    Args:
        vendors: List of unallocated VendorData dataclass instances
        forecast_df: Normalized forecast DataFrame
        worktype_vocab: List of valid worktypes sorted by length (longest first)

    Returns:
        Dict mapping bucket_key to BucketData(vendors=[...], forecast_rows=[...])
        where bucket_key = (platform, location, month, skillset)
    """
    buckets = {}

    logger.info(f"Parsing skills for {len(vendors)} vendors using vocabulary of {len(worktype_vocab)} worktypes")
    logger.info(f"Sample vocabulary (top 5): {worktype_vocab[:5]}")

    # Parse vendor skills and group
    for vendor in vendors:
        # Normalize platform
        platform_norm = vendor.platform.strip().split()[0].upper() if vendor.platform else ''

        # Normalize location
        location_norm = normalize_locality(vendor.location)

        # Parse skills using greedy longest-match-first algorithm
        skillset = parse_vendor_skills(vendor.skills, worktype_vocab)

        if not skillset:
            continue  # Skip vendors with no recognized skills

        # Vendor can work in multiple months - get from StateList months
        # For now, we'll add to buckets when matching forecast rows
        vendor.platform_norm = platform_norm
        vendor.location_norm = location_norm
        vendor.skillset = skillset

    # Group forecast rows and match vendors
    for _, row in forecast_df.iterrows():
        # Use pre-parsed fields for performance
        platform_norm = row['platform_norm']
        location_norm = row['locality_norm']
        month_name = row['month_name']
        worktype_norm = normalize_worktype(row['case_type'])

        if not worktype_norm:
            continue

        # Find vendors with matching skills
        matching_vendors = []
        for vendor in vendors:
            if (vendor.platform_norm == platform_norm and
                vendor.location_norm == location_norm and
                worktype_norm in (vendor.skillset or set())):
                matching_vendors.append(vendor)

        if not matching_vendors:
            continue  # No vendors for this forecast row

        # Create bucket key
        skillset = frozenset([worktype_norm])  # Forecast row has single worktype
        bucket_key = (platform_norm, location_norm, month_name, skillset)

        if bucket_key not in buckets:
            buckets[bucket_key] = BucketData(
                vendors=[],
                forecast_rows=[]
            )

        # Add forecast row
        buckets[bucket_key].forecast_rows.append(_dataframe_row_to_forecast_dict(row))

        # Add vendors (avoid duplicates)
        for vendor in matching_vendors:
            if vendor not in buckets[bucket_key].vendors:
                buckets[bucket_key].vendors.append(vendor)

    logger.info(f"Created {len(buckets)} buckets")
    return buckets


def is_state_compatible(demand_state: str, vendor_state_list: List[str]) -> bool:
    """
    Check if vendor can work on demand with given state.

    Args:
        demand_state: State from forecast row (e.g., "FL", "GA", "N/A")
        vendor_state_list: Vendor's state list (e.g., ['FL', 'GA'])

    Returns:
        True if vendor is compatible with demand state

    Rules:
        - N/A demand → accept any vendor (no state filtering)
        - Specific state → vendor must have that state in their list
    """
    demand_state = str(demand_state).strip().upper()

    # N/A demand accepts any vendor
    if demand_state == 'N/A':
        return True

    # Specific state demand requires exact match
    return demand_state in vendor_state_list


def fill_gaps(
    vendors: List[VendorData],
    forecast_rows: List[ForecastRowDict],
    month_name: str,
    allocated_vendors: Dict[Tuple[str, str], int]
) -> List[AllocationData]:
    """
    Fill gaps (FTE_Avail < FTE_Required) with state-compatible vendors.

    Args:
        vendors: List of vendors in this bucket
        forecast_rows: Filtered forecast rows for this bucket
        month_name: Current month being processed
        allocated_vendors: Dict mapping (CN, month) to forecast_id (REQUIRED, must not be None)

    Returns:
        List of AllocationData dataclass instances

    Note:
        allocated_vendors is modified in place and shared across all bucket iterations
        to prevent duplicate allocations within the same month.
    """
    # Defensive check - allocated_vendors must be provided
    if allocated_vendors is None:
        raise ValueError("allocated_vendors must not be None")

    logger.debug(f"fill_gaps: Starting with {len(allocated_vendors)} already allocated vendors for {month_name}")
    allocations = []
    vendors_copy = vendors.copy()  # Work with copy

    # Find rows with gaps
    gap_rows = [row for row in forecast_rows if row.fte_avail < row.fte_required]

    for row in gap_rows:
        gap = int(row.fte_required - row.fte_avail)
        if gap <= 0:
            continue

        demand_state = str(row.state).strip().upper()

        # Allocate vendors one-by-one to fill gap
        for _ in range(gap):
            # Find compatible vendor (state match + not allocated in this month)
            compatible_vendor = None
            for vendor in vendors_copy:
                allocation_key = (vendor.cn, month_name)
                # CRITICAL: Only check allocated_vendors dict, not vendor.allocated flag
                # The vendor.allocated flag is global across all months, but we need per-month tracking
                if (allocation_key not in allocated_vendors and
                    is_state_compatible(demand_state, vendor.state_list)):
                    compatible_vendor = vendor
                    break

            if compatible_vendor:
                # Allocate this vendor for this month
                allocation_key = (compatible_vendor.cn, month_name)
                allocated_vendors[allocation_key] = row.forecast_id
                logger.debug(f"fill_gaps: Allocated {compatible_vendor.cn} to {month_name}, dict now has {len(allocated_vendors)} entries")

                # Set allocated flag (for backward compatibility, though we primarily use dict)
                compatible_vendor.allocated = True

                allocations.append(AllocationData(
                    forecast_row=row,
                    vendor=compatible_vendor,
                    fte_allocated=1,
                    allocation_type='gap_fill'
                ))

                # Update row's FTE_Avail
                row.fte_avail += 1

                # Remove vendor from available list
                vendors_copy.remove(compatible_vendor)
            else:
                # No compatible vendors left for this state
                logger.warning(f"Could not fill gap for {row.main_lob} {row.state} {row.month_name} - no state-compatible vendors")
                break

    logger.info(f"Filled {len(allocations)} gaps for {month_name}")
    return allocations


def distribute_proportionally(
    vendors: List[VendorData],
    forecast_rows: List[ForecastRowDict],
    month_name: str,
    allocated_vendors: Dict[Tuple[str, str], int]
) -> List[AllocationData]:
    """
    Distribute remaining bench vendors proportionally using Largest Remainder Method.

    Args:
        vendors: List of vendors in this bucket
        forecast_rows: Filtered forecast rows for this bucket
        month_name: Current month being processed
        allocated_vendors: Dict mapping (CN, month) to forecast_id (REQUIRED, must not be None)

    Returns:
        List of AllocationData dataclass instances

    Note:
        allocated_vendors is modified in place and shared across all bucket iterations
        to prevent duplicate allocations within the same month.
    """
    # Defensive check - allocated_vendors must be provided
    if allocated_vendors is None:
        raise ValueError("allocated_vendors must not be None")

    logger.debug(f"distribute_proportionally: Starting with {len(allocated_vendors)} already allocated vendors for {month_name}")
    allocations = []
    # Filter for available vendors (exclude those allocated in this month)
    # CRITICAL: Only check allocated_vendors dict for per-month tracking
    available_vendors = [v for v in vendors
                         if (v.cn, month_name) not in allocated_vendors]

    if not available_vendors:
        logger.info(f"No remaining vendors for {month_name}")
        return allocations

    num_vendors = len(available_vendors)

    # Calculate total demand (forecast volume)
    total_demand = sum(row.forecast for row in forecast_rows)
    if total_demand == 0:
        logger.warning(f"Total forecast volume is zero for {month_name}")
        return allocations

    # Calculate ideal FTE_Avail for each row based on proportional demand
    # Goal: Maintain FTE_Avail / Forecast ratio balanced across all rows
    total_current_fte = sum(row.fte_avail for row in forecast_rows)
    total_available_fte = total_current_fte + num_vendors  # Current + new vendors

    # Calculate ideal target FTE for each row (proportional to its demand)
    ideal_targets = [
        total_available_fte * (row.forecast / total_demand)
        for row in forecast_rows
    ]

    # Calculate how many MORE vendors each row needs to reach its ideal target
    additional_needed = [
        max(0, ideal_target - row.fte_avail)
        for ideal_target, row in zip(ideal_targets, forecast_rows)
    ]

    # Distribute vendors proportionally to additional needs
    total_additional_needed = sum(additional_needed)

    if total_additional_needed > 0:
        # Distribute based on proportional need
        ideal_shares = [
            num_vendors * (need / total_additional_needed)
            for need in additional_needed
        ]
        logger.debug(f"distribute_proportionally: Using proportional-need distribution")
    else:
        # Fallback: All rows at ideal ratio, distribute based on forecast proportions
        ideal_shares = [
            num_vendors * (row.forecast / total_demand)
            for row in forecast_rows
        ]
        logger.debug(f"distribute_proportionally: Using forecast-based distribution (all at ideal ratio)")

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
        demand_state = str(row.state).strip().upper()

        # Allocate 'allocation_count' vendors to this row
        for _ in range(allocation_count):
            if vendor_idx >= len(available_vendors):
                logger.warning(f"Ran out of vendors during proportional distribution")
                break

            # Find next compatible vendor (state match + not allocated in this month)
            compatible_vendor = None
            search_start = vendor_idx
            while vendor_idx < len(available_vendors):
                vendor = available_vendors[vendor_idx]
                allocation_key = (vendor.cn, month_name)
                # CRITICAL: Only check allocated_vendors dict for per-month tracking
                if (allocation_key not in allocated_vendors and
                    is_state_compatible(demand_state, vendor.state_list)):
                    compatible_vendor = vendor
                    break
                vendor_idx += 1

            if compatible_vendor:
                # Allocate this vendor for this month
                allocation_key = (compatible_vendor.cn, month_name)
                allocated_vendors[allocation_key] = row.forecast_id
                logger.debug(f"distribute_proportionally: Allocated {compatible_vendor.cn} to {month_name}, dict now has {len(allocated_vendors)} entries")

                # Set allocated flag (for backward compatibility, though we primarily use dict)
                compatible_vendor.allocated = True

                allocations.append(AllocationData(
                    forecast_row=row,
                    vendor=compatible_vendor,
                    fte_allocated=1,
                    allocation_type='excess_distribution'
                ))

                # Update row's FTE_Avail
                row.fte_avail += 1

                vendor_idx += 1
            else:
                logger.warning(f"Could not allocate vendor to {row.main_lob} {row.state} {row.month_name}")

    logger.info(f"Distributed {len(allocations)} excess vendors for {month_name}")
    return allocations


# ============================================================================
# BENCHALLOCATOR CLASS
# ============================================================================

class BenchAllocator:
    """
    Bench resource allocation system for allocating unallocated (bench) vendors.

    Key features:
    1. Buckets keyed by VENDOR skillset (not forecast worktype)
    2. Sequential allocation per bucket (gap fill → excess distribution)
    3. Consolidated change tracking by (forecast_id, month_index)
    4. Two-cycle state matching (specific states first, then N/A fallback)
    """

    def __init__(
        self,
        execution_id: str,
        month: str,
        year: int,
        core_utils: CoreUtils
    ):
        """
        Initialize BenchAllocator from existing allocation execution.

        Args:
            execution_id: UUID from AllocationExecutionModel
            month: Report month (e.g., "March")
            year: Report year (e.g., 2025)
            core_utils: CoreUtils instance for DB access
        """
        # Store core parameters
        self.execution_id = execution_id
        self.month = month
        self.year = year
        self.core_utils = core_utils

        # Initialize data structures
        self.vendors: List[VendorData] = []
        self.valid_states: set = set()
        self.forecast_df: pd.DataFrame = None
        self.worktype_vocab: List[str] = []

        # Buckets keyed by (platform, location, month, VENDOR_SKILLSET)
        # SIMPLIFIED: Only stores vendor lists (no forecast data)
        self.buckets: Dict[BucketKey, List[VendorData]] = {}

        # Track all allocations (unconsolidated)
        self.allocation_history: List[AllocationData] = []

        # Track allocated vendors by (CN, month) to allow multi-month allocations
        # Maps (vendor_cn, month_name) → forecast_id
        self.allocated_vendors: Dict[Tuple[str, str], int] = {}

        # Consolidation cache - stores computed consolidation result to avoid redundant computation
        # Cache is invalidated when allocation_history changes (after allocate() runs)
        self._consolidated_cache: Optional[Dict[Tuple[int, int], Dict]] = None
        self._cache_valid: bool = False

        # Initialize
        logger.info(f"Initializing BenchAllocator for {month} {year} (execution: {execution_id})")
        self._load_unallocated_vendors()
        self._load_and_normalize_forecast_data()
        self._build_worktype_vocabulary()
        self._initialize_buckets()

        logger.info(f"✓ BenchAllocator initialized:")
        logger.info(f"  - Vendors: {len(self.vendors)}")
        logger.info(f"  - Buckets: {len(self.buckets)}")
        logger.info(f"  - Forecast rows: {len(self.forecast_df)}")

    def _load_unallocated_vendors(self):
        """Load unallocated vendors from roster_allotment report."""
        self.vendors, self.valid_states = get_unallocated_vendors_with_states(
            self.execution_id,
            self.month,
            self.year,
            self.core_utils
        )
        logger.info(f"Loaded {len(self.vendors)} unallocated vendors")
        logger.info(f"Valid states: {sorted(self.valid_states)}")

    def _load_and_normalize_forecast_data(self):
        """Load ForecastModel and normalize Month1-Month6 to individual rows."""
        self.forecast_df = normalize_forecast_data(
            self.month,
            self.year,
            self.core_utils
        )
        logger.info(f"Loaded {len(self.forecast_df)} normalized forecast rows")

    def _build_worktype_vocabulary(self):
        """Extract unique worktypes from forecast, sorted longest-first."""
        self.worktype_vocab = build_worktype_vocabulary(self.forecast_df)
        logger.info(f"Built vocabulary with {len(self.worktype_vocab)} worktypes")
        logger.info(f"Sample: {self.worktype_vocab[:5]}")

    def _initialize_buckets(self):
        """
        Group vendors by (platform, location, month, state_set, skillset).

        State-based bucketing with empty set handling:
        - Vendors with US state codes → state_set = frozenset({'FL', 'GA', ...})
        - Vendors with N/A only → state_set = frozenset() (empty)

        SIMPLIFIED: Only vendors, no forecast data pre-population.
        Forecast data will be filtered on-demand during allocation with state filtering.
        """
        buckets = {}

        logger.info(f"Parsing skills for {len(self.vendors)} vendors...")

        # Get unique months from forecast (for bucket creation)
        unique_months = self.forecast_df['month_name'].unique()

        # Parse vendor skills and create buckets
        for vendor in self.vendors:
            # Normalize platform/location
            platform_norm = vendor.platform.strip().split()[0].upper() if vendor.platform else ''
            location_norm = normalize_locality(vendor.location)

            # Parse vendor's full skillset
            skillset = parse_vendor_skills(vendor.skills, self.worktype_vocab)

            if not skillset:
                logger.debug(f"Skipping vendor {vendor.cn} - no recognized skills")
                continue

            # Extract vendor's state_set (excluding N/A for specific states)
            # If vendor has only N/A, state_set will be empty frozenset()
            vendor_state_set = frozenset(
                state for state in vendor.state_list
                if state != 'N/A'
            )
            # If all states were N/A, state_set remains empty
            if not vendor_state_set:
                vendor_state_set = frozenset()

            # Store normalized fields in vendor
            vendor.platform_norm = platform_norm
            vendor.location_norm = location_norm
            vendor.skillset = skillset

            # Create bucket for each month
            for month_name in unique_months:
                bucket_key = (platform_norm, location_norm, month_name, vendor_state_set, skillset)

                if bucket_key not in buckets:
                    buckets[bucket_key] = []  # Just list of vendors

                # Add vendor to bucket (avoid duplicates)
                if vendor not in buckets[bucket_key]:
                    buckets[bucket_key].append(vendor)

        self.buckets = buckets

        logger.info(f"✓ Initialized {len(self.buckets)} buckets (vendors only, no forecast rows)")
        logger.info(f"  - Total vendors grouped: {sum(len(v) for v in buckets.values())}")

    def _filter_forecast_for_bucket(
        self,
        platform: str,
        location: str,
        month_name: str,
        state_set: frozenset[str],
        skillset: frozenset[str]
    ) -> List[ForecastRowDict]:
        """
        Filter forecast data for specific bucket with state filtering.

        This method performs on-demand filtering based on bucket key.
        Implements state-based filtering:
        - If state_set is non-empty: Filter forecast rows where state IN state_set
        - If state_set is empty: Filter forecast rows where state = 'N/A'

        Args:
            platform: Normalized platform (e.g., "AMISYS")
            location: Normalized location (e.g., "Domestic")
            month_name: Month name (e.g., "April")
            state_set: Vendor state set (e.g., frozenset({'FL', 'GA'})) or frozenset() for N/A
            skillset: Vendor skillset (e.g., frozenset({'ftc', 'adj'}))

        Returns:
            List of ForecastRowDict matching the bucket criteria
        """
        forecast_rows = []

        # For each worktype in the vendor skillset
        for worktype in skillset:
            # Base filtering conditions (using pre-parsed fields for performance)
            base_filter = (
                (self.forecast_df['platform_norm'] == platform) &
                (self.forecast_df['locality_norm'] == location) &
                (self.forecast_df['month_name'] == month_name) &
                (self.forecast_df['case_type'].apply(normalize_worktype) == worktype)
            )

            # Apply state filtering based on state_set
            if state_set:  # Non-empty (specific states)
                # Filter forecast rows where state IN state_set
                candidate_rows = self.forecast_df[
                    base_filter &
                    (self.forecast_df['state'].isin(list(state_set)))
                ]
            else:  # Empty state_set (N/A vendors)
                # Filter forecast rows where state = 'N/A'
                candidate_rows = self.forecast_df[
                    base_filter &
                    (self.forecast_df['state'] == 'N/A')
                ]

            if candidate_rows.empty:
                continue

            # Convert to forecast row dicts
            for _, row in candidate_rows.iterrows():
                forecast_row = _dataframe_row_to_forecast_dict(row)
                if forecast_row not in forecast_rows:
                    forecast_rows.append(forecast_row)

        return forecast_rows

    def _update_forecast_dataframe(self, forecast_rows: List[ForecastRowDict]):
        """
        Update self.forecast_df with changes from allocated forecast rows.

        This ensures subsequent bucket iterations see the updated fte_avail and capacity values.
        CRITICAL FIX: Without this, each bucket sees stale data from DataFrame, causing:
        - Gap filling to happen multiple times for the same forecast
        - Proportional distribution to calculate with incomplete data
        - Over-allocation and incorrect ratio balancing

        Args:
            forecast_rows: List of ForecastRowDict instances that were modified during allocation
        """
        if not forecast_rows:
            return

        for forecast_row in forecast_rows:
            # Find the row in DataFrame matching this forecast_id and month_name
            mask = (
                (self.forecast_df['forecast_id'] == forecast_row.forecast_id) &
                (self.forecast_df['month_name'] == forecast_row.month_name)
            )

            # Update fte_avail and capacity with the modified values
            if mask.any():
                self.forecast_df.loc[mask, 'fte_avail'] = forecast_row.fte_avail
                self.forecast_df.loc[mask, 'capacity'] = forecast_row.capacity
                logger.debug(
                    f"Updated DataFrame: forecast_id={forecast_row.forecast_id}, "
                    f"month={forecast_row.month_name}, fte_avail={forecast_row.fte_avail}, "
                    f"capacity={forecast_row.capacity}"
                )

    def allocate(self) -> int:
        """
        Run allocation process: iterate buckets, run gap fill + excess distribution per bucket.

        CRITICAL FIXES:
        1. Sequential allocation per bucket (not global phases)
        2. DataFrame update after each bucket to propagate changes
           - Without this, subsequent buckets see stale data
           - Causes gap filling multiple times and incorrect proportional distribution
        3. State-based bucketing: non-empty state_set buckets processed first,
           then empty state_set buckets (N/A vendors), creating natural two-cycle behavior

        Returns:
            Total number of vendors allocated (unconsolidated)
        """
        total_allocated = 0

        logger.info(f"Starting allocation for {len(self.buckets)} buckets...")

        # Iterate buckets (sorted for deterministic behavior)
        # Note: Non-empty state_set buckets will sort before empty ones naturally
        for bucket_key in sorted(self.buckets.keys()):
            vendors = self.buckets[bucket_key]  # Just vendor list now
            platform, location, month_name, state_set, skillset = bucket_key  # Updated unpacking

            # Format state_set for logging
            state_str = ', '.join(sorted(state_set)) if state_set else 'N/A'
            skillset_str = ' + '.join(sorted(skillset))
            logger.info(f"\nProcessing bucket: {platform} | {location} | {month_name} | States: {state_str} | Skills: {skillset_str}")
            logger.info(f"  - Vendors in bucket: {len(vendors)}")
            logger.info(f"  - Already allocated (all months): {len(self.allocated_vendors)}")

            # Filter forecast data for this bucket on-demand (with state filtering)
            forecast_rows = self._filter_forecast_for_bucket(platform, location, month_name, state_set, skillset)

            if not forecast_rows:
                logger.info(f"  - No forecast rows for bucket, skipping")
                continue

            logger.info(f"  - Forecast rows filtered: {len(forecast_rows)}")

            # Phase 1: Fill gaps for this bucket
            gap_allocations = fill_gaps(vendors, forecast_rows, month_name, self.allocated_vendors)
            self.allocation_history.extend(gap_allocations)
            total_allocated += len(gap_allocations)

            logger.info(f"  → Gap fill: {len(gap_allocations)} vendors")

            # Phase 2: Distribute excess for this bucket
            excess_allocations = distribute_proportionally(vendors, forecast_rows, month_name, self.allocated_vendors)
            self.allocation_history.extend(excess_allocations)
            total_allocated += len(excess_allocations)

            logger.info(f"  → Excess distribution: {len(excess_allocations)} vendors")

            # CRITICAL: Update DataFrame with changes from this bucket
            # This ensures next bucket iterations see the updated fte_avail and capacity values
            self._update_forecast_dataframe(forecast_rows)
            logger.info(f"  ✓ Updated DataFrame with {len(forecast_rows)} forecast row changes")

        logger.info(f"\n✓ Allocation complete: {total_allocated} total allocations (unconsolidated)")

        # Invalidate consolidation cache since allocation_history has changed
        self._cache_valid = False

        return total_allocated

    def consolidate_changes(self) -> Dict[Tuple[int, int], Dict]:
        """
        Consolidate allocation history by (forecast_id, month_index).
        Uses cached result if available to avoid redundant computation.

        CRITICAL: Same forecast_id can be updated in multiple bucket iterations.
        This consolidation aggregates all changes for the same forecast row.

        Returns:
            Dict mapping (forecast_id, month_index) to consolidated change data
        """
        # Return cached result if valid
        if self._cache_valid and self._consolidated_cache is not None:
            logger.debug(f"Returning cached consolidation ({len(self._consolidated_cache)} rows)")
            return self._consolidated_cache

        consolidated = {}

        # PHASE 1: Collect vendors and count allocations (no capacity calculations)
        for alloc in self.allocation_history:
            key = (alloc.forecast_row.forecast_id, alloc.forecast_row.month_index)

            if key not in consolidated:
                consolidated[key] = {
                    'forecast_row': alloc.forecast_row,
                    'vendors': [],
                    'gap_fill_count': 0,
                    'excess_count': 0
                }

            consolidated[key]['vendors'].append(alloc.vendor)

            if alloc.allocation_type == 'gap_fill':
                consolidated[key]['gap_fill_count'] += 1
            else:
                consolidated[key]['excess_count'] += 1

        # PHASE 2: Compute totals vectorized (once per forecast)
        for key, data in consolidated.items():
            total_vendors = len(data['vendors'])

            # Total FTE change = count of vendors (each vendor = 1 FTE)
            data['total_fte_change'] = total_vendors

            # Calculate capacity ONCE for all vendors
            data['total_capacity_change'] = self._calculate_capacity_for_fte(
                data['forecast_row'],
                total_vendors  # All vendors at once
            )

        # Cache the result for subsequent calls
        self._consolidated_cache = consolidated
        self._cache_valid = True

        logger.info(f"✓ Consolidated {len(self.allocation_history)} allocations into {len(consolidated)} unique forecast rows (cached)")

        return consolidated

    def _calculate_capacity_for_fte(
        self,
        forecast_row: ForecastRowDict,
        fte_count: int
    ) -> int:
        """
        Calculate capacity for given FTE count using month configuration.

        Formula: capacity = fte_count × target_cph × work_hours × occupancy × (1 - shrinkage) × working_days
        """
        # Get month config using pre-parsed locality
        config = get_specific_config(
            forecast_row.month_name,
            forecast_row.month_year,
            forecast_row.locality_norm  # Use pre-parsed field
        )

        # Calculate capacity using month-specific configuration
        # Formula: Capacity = FTE × WorkingDays × WorkHours × Occupancy × (1 - Shrinkage) × TargetCPH
        capacity = (
            fte_count *
            config['working_days'] *
            config['work_hours'] *
            config['occupancy'] *
            (1 - config['shrinkage']) *
            forecast_row.target_cph
        )

        return int(capacity)

    def update_reports(self):
        """
        Update both roster_allotment and bucket_after_allocation reports.

        Should be called after allocation is complete.
        """
        logger.info("Updating allocation reports with bench allocation results...")

        # Update roster allotment report with vendor-to-forecast mapping
        self._update_roster_allotment_report()

        # Update bucket after allocation report
        self._update_bucket_after_allocation_report()

        logger.info("Report updates completed successfully")

    def _update_roster_allotment_report(self):
        """
        Update existing roster_allotment report with bench allocation results.

        Updates:
        1. Status column: 'Not Allocated' → 'Allocated (Bench)'
        2. Month columns: 'Not Allocated' → 'Main LOB | State | Case Type'

        Format: "Amisys Medicaid | FL | FTC-Basic/Non MMP"
        """
        consolidated = self.consolidate_changes()

        # Group allocations by vendor
        vendor_allocations: Dict[str, List[Tuple[str, str]]] = {}  # CN → [(month, allocation_string)]

        for (forecast_id, month_index), change_data in consolidated.items():
            forecast_row = change_data['forecast_row']
            vendors = change_data['vendors']

            # Use pre-parsed fields
            lob_name = forecast_row.market  # Use pre-parsed market field (was incorrectly looking for 'lob_name')
            state = forecast_row.state
            case_type = forecast_row.case_type
            month_name = forecast_row.month_name

            # Create allocation string: "LOB | State | Case Type"
            allocation_string = f"{lob_name} | {state} | {case_type}"

            # Record allocation for each vendor
            for vendor in vendors:
                if vendor.cn not in vendor_allocations:
                    vendor_allocations[vendor.cn] = []
                vendor_allocations[vendor.cn].append((month_name, allocation_string))

        if not vendor_allocations:
            logger.info("No vendor allocations to update in roster_allotment report")
            return

        # Update roster_allotment report in database
        import pandas as pd
        from datetime import datetime

        db_manager = self.core_utils.get_db_manager(
            AllocationReportsModel,
            limit=None,
            skip=0,
            select_columns=None
        )

        with db_manager.SessionLocal() as session:
            # Fetch the SINGLE roster_allotment report for this execution (not per-vendor)
            statement = select(AllocationReportsModel).where(
                and_(
                    AllocationReportsModel.execution_id == self.execution_id,
                    AllocationReportsModel.ReportType == 'roster_allotment'  # Correct field name
                )
            )
            report_row = session.exec(statement).first()

            if not report_row:
                logger.warning(f"Roster allotment report not found for execution {self.execution_id}")
                return

            # Parse JSON string to DataFrame
            report_json = report_row.ReportData  # Correct attribute name
            df = pd.read_json(report_json)

            logger.info(f"Loaded roster_allotment DataFrame: {len(df)} vendors, {len(df.columns)} columns")

            # Update all allocated vendors
            updated_count = 0
            for cn, allocations in vendor_allocations.items():
                # Find vendor row(s) by CN
                vendor_mask = df['CN'] == cn

                if not vendor_mask.any():
                    logger.warning(f"Vendor CN {cn} not found in roster_allotment report")
                    continue

                # Update Status column
                df.loc[vendor_mask, 'Status'] = 'Allocated (Bench)'

                # Update month columns
                for month_name, allocation_string in allocations:
                    # Month column format: "April 2025_LOB" (already includes year)
                    month_col_lob = f"{month_name}_LOB"

                    if month_col_lob in df.columns:
                        df.loc[vendor_mask, month_col_lob] = allocation_string
                        updated_count += 1
                    else:
                        logger.warning(f"Column {month_col_lob} not found in roster_allotment DataFrame")

            logger.info(f"Updated roster_allotment for {len(vendor_allocations)} vendors ({updated_count} month allocations)")

            # Convert DataFrame back to JSON string
            updated_json = df.to_json(orient='records', date_format='iso')
            report_row.ReportData = updated_json  # Correct attribute name

            # Update metadata
            report_row.UpdatedDateTime = datetime.now()
            report_row.UpdatedBy = 'bench_allocation'

            session.add(report_row)
            session.commit()

            logger.info(f"✓ Updated roster_allotment report in database for execution {self.execution_id}")

    def _update_bucket_after_allocation_report(self):
        """
        Create/update bucket_after_allocation report with consolidated changes.

        Shows bucket state after bench allocation (FTE_Avail, Capacity updated).
        """
        consolidated = self.consolidate_changes()

        # Generate bucket after allocation data
        bucket_data = self._generate_buckets_after_allocation(consolidated)

        # Store in AllocationReportsModel using proper session management
        db_manager = self.core_utils.get_db_manager(
            AllocationReportsModel,
            limit=None,
            skip=0,
            select_columns=None
        )

        with db_manager.SessionLocal() as session:
            for bucket_row in bucket_data:
                report_row = AllocationReportsModel(
                    execution_id=self.execution_id,
                    report_type='bucket_after_allocation',
                    cn=None,  # Not vendor-specific
                    report_data=bucket_row
                )
                session.add(report_row)

            session.commit()
            logger.info(f"Created bucket_after_allocation report with {len(bucket_data)} rows")

    def _generate_buckets_after_allocation(self, consolidated: Dict) -> List[Dict]:
        """
        Generate bucket summary data after allocation.

        Returns list of dicts with bucket state (FTE, Capacity after bench allocation).
        """
        bucket_rows = []

        for (forecast_id, month_index), change_data in consolidated.items():
            forecast_row = change_data['forecast_row']

            bucket_rows.append({
                'Main_LOB': forecast_row.main_lob,
                'State': forecast_row.state,
                'Case_Type': forecast_row.case_type,
                'Target_CPH': forecast_row.target_cph,
                'Month': forecast_row.month_name,
                'Month_Year': forecast_row.month_year,
                'Month_Index': month_index,
                'FTE_Required': forecast_row.fte_required,
                'FTE_Avail': forecast_row.fte_avail,  # Updated value
                'Capacity': forecast_row.capacity,  # Updated value
                'Gap_Fill_Count': change_data['gap_fill_count'],
                'Excess_Count': change_data['excess_count'],
                'Total_Vendors_Allocated': len(change_data['vendors'])
            })

        return bucket_rows

    def export_to_excel(self, output_path: str):
        """
        Export consolidated allocation changes to Excel.

        Format: One row per (forecast_id, month) with before/after values.

        Columns:
        - Main_LOB, State, Case_Type, Target_CPH, Month, Month_Index
        - FTE_Avail_Before, FTE_Avail_After, FTE_Change
        - Capacity_Before, Capacity_After, Capacity_Change
        - Gap_Fill_Count, Excess_Distribution_Count, Total_Vendors_Allocated
        - Vendor_Details (comma-separated CN list)
        """
        consolidated = self.consolidate_changes()

        # Prepare data for Excel export
        changes_data = self._prepare_changes_data(consolidated)
        summary_data = self._prepare_summary_data(consolidated)

        # Create Excel workbook
        from code.logics.bench_allocation_export import create_changes_workbook

        create_changes_workbook(
            changes_data=changes_data,
            summary_data=summary_data,
            month=self.month,
            year=self.year,
            output_path=output_path
        )

        logger.info(f"Exported bench allocation changes to {output_path}")

    def _prepare_changes_data(self, consolidated: Dict) -> List[Dict]:
        """
        Prepare consolidated changes data for Excel export.

        One row per (forecast_id, month) with before/after values.
        """
        changes_rows = []

        for (forecast_id, month_index), change_data in consolidated.items():
            forecast_row = change_data['forecast_row']
            vendors = change_data['vendors']

            # Calculate before values (subtract total changes)
            fte_after = forecast_row.fte_avail
            capacity_after = forecast_row.capacity
            fte_change = change_data['total_fte_change']
            capacity_change = change_data['total_capacity_change']

            fte_before = fte_after - fte_change
            capacity_before = capacity_after - capacity_change

            # Vendor details
            vendor_details = ', '.join([f"{v.first_name} {v.last_name} ({v.cn})" for v in vendors])

            changes_rows.append({
                'Main_LOB': forecast_row.main_lob,
                'State': forecast_row.state,
                'Case_Type': forecast_row.case_type,
                'Target_CPH': forecast_row.target_cph,
                'Month': f"{forecast_row.month_name} {forecast_row.month_year}",
                'Month_Index': month_index,
                'FTE_Avail_Before': fte_before,
                'FTE_Avail_After': fte_after,
                'FTE_Change': fte_change,
                'Capacity_Before': capacity_before,
                'Capacity_After': capacity_after,
                'Capacity_Change': capacity_change,
                'Gap_Fill_Count': change_data['gap_fill_count'],
                'Excess_Distribution_Count': change_data['excess_count'],
                'Total_Vendors_Allocated': len(vendors),
                'Vendor_Details': vendor_details
            })

        return changes_rows

    def _prepare_summary_data(self, consolidated: Dict) -> Dict:
        """
        Prepare summary statistics for Excel export.
        """
        total_vendors = set()
        total_gap_fills = 0
        total_excess = 0
        total_fte_change = 0
        total_capacity_change = 0

        for change_data in consolidated.values():
            for vendor in change_data['vendors']:
                total_vendors.add(vendor.cn)
            total_gap_fills += change_data['gap_fill_count']
            total_excess += change_data['excess_count']
            total_fte_change += change_data['total_fte_change']
            total_capacity_change += change_data['total_capacity_change']

        return {
            'total_vendors_allocated': len(total_vendors),
            'total_forecast_rows_modified': len(consolidated),
            'total_gap_fills': total_gap_fills,
            'total_excess_distributed': total_excess,
            'total_fte_change': total_fte_change,
            'total_capacity_change': total_capacity_change
        }


def allocate_bench_for_month(
    month: str,
    year: int,
    core_utils: CoreUtils,
    execution_id: str = None
) -> AllocationResult:
    """
    Main orchestration function for bench allocation using BenchAllocator class.

    Args:
        month: Month name (e.g., "January")
        year: Year (e.g., 2025)
        core_utils: CoreUtils instance for database access
        execution_id: Optional execution ID (if not provided, will validate and get current)

    Returns:
        AllocationResult with:
        - success: bool
        - month: str
        - year: int
        - total_bench_allocated: int
        - gaps_filled: int
        - excess_distributed: int
        - rows_modified: int
        - allocations: List[AllocationRecord]
        - error: str (if failed)
    """
    try:
        logger.info(f"=== Starting bench allocation for {month} {year} ===")

        # Step 1: Validate allocation is current (if execution_id not provided)
        if not execution_id:
            validity_check = validate_allocation_is_current(month, year, core_utils)
            if not validity_check['valid']:
                logger.error(f"Allocation validation failed: {validity_check.get('error')}")
                return AllocationResult(
                    success=False,
                    month=month,
                    year=year,
                    total_bench_allocated=0,
                    gaps_filled=0,
                    excess_distributed=0,
                    rows_modified=0,
                    allocations=[],
                    error=validity_check.get('error')
                )
            execution_id = validity_check['execution_id']

        logger.info(f"✓ Using execution ID: {execution_id}")

        # Step 2: Initialize BenchAllocator
        allocator = BenchAllocator(
            execution_id=execution_id,
            month=month,
            year=year,
            core_utils=core_utils
        )

        # Check if there are vendors to allocate
        if not allocator.vendors:
            logger.info("No unallocated vendors found")
            return AllocationResult(
                success=True,
                month=month,
                year=year,
                total_bench_allocated=0,
                gaps_filled=0,
                excess_distributed=0,
                rows_modified=0,
                allocations=[]
            )

        logger.info(f"✓ Found {len(allocator.vendors)} unallocated vendors")
        logger.info(f"✓ Created {len(allocator.buckets)} buckets")

        # Step 3: Run allocation
        total_allocated = allocator.allocate()

        logger.info(f"✓ Total allocations: {total_allocated}")

        # Step 4: Consolidate changes
        consolidated = allocator.consolidate_changes()

        # Step 5: Update reports
        allocator.update_reports()

        # Step 6: Prepare summary statistics
        gaps_filled = sum(data['gap_fill_count'] for data in consolidated.values())
        excess_distributed = sum(data['excess_count'] for data in consolidated.values())

        # Step 7: Convert consolidated data to AllocationRecord format
        allocation_records = []
        for (forecast_id, month_index), change_data in consolidated.items():
            forecast_row = change_data['forecast_row']
            vendors = change_data['vendors']

            # Convert ForecastRowDict to ForecastRowData for response
            forecast_row_data = ForecastRowData(
                forecast_id=forecast_row.forecast_id,
                main_lob=forecast_row.main_lob,
                state=forecast_row.state,
                case_type=forecast_row.case_type,
                target_cph=forecast_row.target_cph,
                month_name=forecast_row.month_name,
                month_year=forecast_row.month_year,
                month_index=forecast_row.month_index,
                forecast=forecast_row.forecast,
                fte_required=forecast_row.fte_required,
                fte_avail=forecast_row.fte_avail,
                fte_avail_original=forecast_row.fte_avail_original,
                capacity=forecast_row.capacity,
                capacity_original=forecast_row.capacity_original
            )

            # Convert VendorData to VendorAllocation for response
            vendor_allocations = [
                VendorAllocation(
                    first_name=v.first_name,
                    last_name=v.last_name,
                    cn=v.cn,
                    platform=v.platform,
                    location=v.location,
                    skills=v.skills,
                    state_list=v.state_list,
                    original_state=v.state,
                    allocated=v.allocated
                )
                for v in vendors
            ]

            allocation_record = AllocationRecord(
                forecast_row=forecast_row_data,
                vendors=vendor_allocations,
                gap_fill_count=change_data['gap_fill_count'],
                excess_distribution_count=change_data['excess_count'],
                fte_change=change_data['total_fte_change'],
                capacity_change=change_data['total_capacity_change']
            )
            allocation_records.append(allocation_record)

        logger.info(f"\n=== Allocation Complete ===")
        logger.info(f"Total allocated: {total_allocated}")
        logger.info(f"Gaps filled: {gaps_filled}")
        logger.info(f"Excess distributed: {excess_distributed}")
        logger.info(f"Rows modified: {len(consolidated)}")

        return AllocationResult(
            success=True,
            month=month,
            year=year,
            total_bench_allocated=total_allocated,
            gaps_filled=gaps_filled,
            excess_distributed=excess_distributed,
            rows_modified=len(consolidated),
            allocations=allocation_records
        )

    except Exception as e:
        logger.error(f"Error during bench allocation: {e}", exc_info=True)
        return AllocationResult(
            success=False,
            month=month,
            year=year,
            total_bench_allocated=0,
            gaps_filled=0,
            excess_distributed=0,
            rows_modified=0,
            allocations=[],
            error=str(e)
        )

