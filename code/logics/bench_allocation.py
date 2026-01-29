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
import os
import numpy as np
from io import StringIO

from code.settings import BASE_DIR
from code.logics.core_utils import CoreUtils
from code.logics.db import AllocationReportsModel, ForecastModel, MonthConfigurationModel
from code.logics.allocation import parse_main_lob, normalize_locality, Calculations
from code.logics.allocation_validity import validate_allocation_is_current
from code.logics.month_config_utils import get_specific_config

logger = logging.getLogger(__name__)


# ============================================================================
# TYPE-SAFE DATA STRUCTURES
# ============================================================================

@dataclass
class VendorAllocation:
    """Single vendor allocation details with month-specific metadata"""
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

    # Month-specific fields (NEW - for month-segregated allocation)
    month_name: str = ''  # e.g., "May"
    month_year: int = 0   # e.g., 2025
    month_index: int = 0  # 1-6 (which MonthX column this represents)

    # Normalized fields for bucketing (previously in VendorData)
    platform_norm: Optional[str] = None
    location_norm: Optional[str] = None
    skillset: Optional[frozenset[str]] = None

    def __hash__(self):
        """Hash based on CN for use in sets/dicts"""
        return hash(self.cn)

    def __eq__(self, other):
        """Equality based on CN"""
        if not isinstance(other, VendorAllocation):
            return False
        return self.cn == other.cn


@dataclass
class ForecastRowData:
    """Forecast row data with allocation updates"""
    forecast_id: int  # ForecastModel.id (database primary key, used for updates)
    call_type_id: str  # Centene_Capacity_Plan_Call_Type_ID (business identifier)
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
    """
    Complete allocation result with type safety.

    Provides structured result with clear success/failure indication
    and detailed error information when failures occur.
    """
    success: bool
    month: str
    year: int
    total_bench_allocated: int
    gaps_filled: int
    excess_distributed: int
    rows_modified: int
    allocations: List[AllocationRecord]
    error: str = ""  # Only populated if success=False
    recommendation: Optional[str] = None  # Actionable recommendation on errors
    context: Optional[Dict] = None  # Additional context for errors
    info_message: Optional[str] = None  # For success with warnings/info

    def to_dict(self) -> Dict:
        """Convert to API response format."""
        result = {
            "success": self.success,
            "month": self.month,
            "year": self.year,
            "total_bench_allocated": self.total_bench_allocated,
            "gaps_filled": self.gaps_filled,
            "excess_distributed": self.excess_distributed,
            "rows_modified": self.rows_modified,
            "allocations_count": len(self.allocations)
        }

        if self.error:
            result["error"] = self.error

        if self.recommendation:
            result["recommendation"] = self.recommendation

        if self.context:
            result["context"] = self.context

        if self.info_message:
            result["info_message"] = self.info_message

        return result


# ============================================================================
# NEW DATACLASS STRUCTURES (REPLACING TYPEDDICT)
# ============================================================================

@dataclass(frozen=True)
class MonthData:
    """Month mapping data (immutable)"""
    month: str
    year: int


# VendorData dataclass removed - replaced by VendorAllocation throughout


@dataclass
class ForecastRowDict:
    """Mutable forecast row data used during allocation processing"""
    forecast_id: int  # ForecastModel.id (database primary key, used for updates)
    call_type_id: str  # Centene_Capacity_Plan_Call_Type_ID (business identifier)
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
    vendor: VendorAllocation  # Changed from VendorData
    fte_allocated: int
    allocation_type: str  # 'gap_fill' or 'excess_distribution'


@dataclass
class BucketData:
    """Bucket data structure (mutable for algorithm efficiency)"""
    vendors: List[VendorAllocation]  # Changed from VendorData
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


class VendorAvailabilityFilter:
    """
    Helper class to filter vendors based on availability across forecast months.

    Stores month names as instance attribute for better performance when
    applying filter to large DataFrames (avoids parameter passing overhead).
    """

    def __init__(self, forecast_months: List[str]):
        """
        Initialize filter with forecast month names.

        Args:
            forecast_months: List of 6 month names from ForecastMonthsModel
        """
        self.forecast_months = forecast_months

    def is_vendor_available(self, row: pd.Series) -> bool:
        """
        Check if vendor is unallocated in ANY month.

        Logic:
        1. If Status == 'Not Allocated' → return True
        2. Else check each {month}_LOB column → return True if ANY is 'Not Allocated'
        3. Else return False

        Args:
            row: DataFrame row (vendor record)

        Returns:
            True if vendor should be included for bench allocation
        """
        # Completely unallocated vendors
        if row.get('Status') == 'Not Allocated':
            return True

        # Check each month's LOB column
        for month_name in self.forecast_months:
            lob_col = f"{month_name}_LOB"
            if lob_col in row.index and row.get(lob_col) == 'Not Allocated':
                return True

        return False


def get_unallocated_vendors_with_states(
    execution_id: str,
    month: str,
    year: int,
    core_utils: CoreUtils,
    forecast_months: Optional[List[str]] = None
) -> Tuple[Dict[Tuple[str, int], List[VendorAllocation]], set[str]]:
    """
    Get vendors unallocated per month, segregated by month into a dictionary.

    CRITICAL CHANGE: Returns month-segregated dictionary instead of flat list.
    Vendors are grouped by (month_name, month_year) with separate VendorAllocation
    instances for each month they're unallocated.

    Args:
        execution_id: The execution UUID from AllocationExecutionModel
        month: Report month name (e.g., "March") - used for month mappings
        year: Report year (e.g., 2025) - used for month mappings
        core_utils: CoreUtils instance for database access
        forecast_months: Optional pre-loaded list of 6 month names from ForecastMonthsModel.
                        If provided, skips some database queries.

    Returns:
        Tuple of (vendor_dict, valid_states_set)
        - vendor_dict: Dict mapping (month_name, month_year) → List[VendorAllocation]
        - valid_states_set: Set of valid states from forecast data

    Raises:
        RosterAllotmentNotFoundException: If roster_allotment report not found
        EmptyRosterAllotmentException: If roster_allotment report is empty
    """
    import json
    from code.logics.db import ForecastMonthsModel, AllocationExecutionModel
    from code.logics.exceptions import RosterAllotmentNotFoundException, EmptyRosterAllotmentException

    db_manager = core_utils.get_db_manager(AllocationReportsModel, limit=None, skip=0, select_columns=None)

    # Step 1: Load roster_allotment report DataFrame
    with db_manager.SessionLocal() as session:
        report = session.query(AllocationReportsModel).filter(
            AllocationReportsModel.execution_id == execution_id,
            AllocationReportsModel.ReportType == 'roster_allotment'
        ).first()

        if not report:
            raise RosterAllotmentNotFoundException(execution_id, month, year)

        # Parse JSON report data to DataFrame
        report_data = json.loads(report.ReportData)
        report_df = pd.DataFrame(report_data)

        if report_df.empty:
            raise EmptyRosterAllotmentException(execution_id, month, year)

    # Step 2: Get uploaded_file from execution (needed for month mappings)
    exec_db = core_utils.get_db_manager(AllocationExecutionModel, limit=None, skip=0, select_columns=None)
    with exec_db.SessionLocal() as exec_session:
        execution = exec_session.query(AllocationExecutionModel).filter(
            AllocationExecutionModel.execution_id == execution_id
        ).first()

        if not execution:
            raise ValueError(f"Execution {execution_id} not found")

        uploaded_file = execution.ForecastFilename

    # Step 3: Get month mappings using helper function
    month_mappings = get_month_mappings_from_db(
        core_utils=core_utils,
        uploaded_file=uploaded_file,
        report_month=month,
        report_year=year,
        months_record=None  # Will query database
    )
    logger.info(f"Using month mappings: {[(i, f'{m.month} {m.year}') for i, m in month_mappings.items()]}")

    # Step 4: Get valid states from forecast data for state parsing
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

    # Step 5: Create month-segregated vendor dictionary
    vendor_dict = {}  # {(month_name, month_year): [VendorAllocation, ...]}

    for _, row in report_df.iterrows():
        # Parse base vendor fields (once per vendor)
        vendor_cn = row.get('CN', '')
        first_name = row.get('FirstName', '')
        last_name = row.get('LastName', '')
        platform = row.get('PrimaryPlatform', '')
        location = row.get('Location', '')
        skills = row.get('NewWorkType', '')
        original_state = row.get('State', '')
        part_of_production = row.get('PartOfProduction', '')

        # Parse state list (once per vendor)
        state_list = parse_vendor_state_list(original_state, valid_states)

        # Check Status column - if 'Not Allocated', add to ALL months
        status = row.get('Status', '')

        if status == 'Not Allocated':
            # Vendor never allocated - add to ALL 6 months
            for month_idx in range(1, 7):
                month_data = month_mappings[month_idx]
                month_key = (month_data.month, month_data.year)

                if month_key not in vendor_dict:
                    vendor_dict[month_key] = []

                vendor_dict[month_key].append(VendorAllocation(
                    first_name=first_name,
                    last_name=last_name,
                    cn=vendor_cn,
                    platform=platform,
                    location=location,
                    skills=skills,
                    state_list=state_list,
                    original_state=original_state,
                    allocated=False,
                    part_of_production=part_of_production,
                    # NEW: Month-specific fields
                    month_name=month_data.month,
                    month_year=month_data.year,
                    month_index=month_idx
                ))
        else:
            # Status is 'Allocated' - check individual month columns
            for month_idx in range(1, 7):
                month_data = month_mappings[month_idx]
                month_key = (month_data.month, month_data.year)

                # Check {month}_LOB column
                lob_col = f"{month_data.month}_LOB"

                # Only add if column exists AND value is 'Not Allocated'
                if lob_col in row.index and row.get(lob_col) == 'Not Allocated':
                    if month_key not in vendor_dict:
                        vendor_dict[month_key] = []

                    vendor_dict[month_key].append(VendorAllocation(
                        first_name=first_name,
                        last_name=last_name,
                        cn=vendor_cn,
                        platform=platform,
                        location=location,
                        skills=skills,
                        state_list=state_list,
                        original_state=original_state,
                        allocated=False,
                        part_of_production=part_of_production,
                        # NEW: Month-specific fields
                        month_name=month_data.month,
                        month_year=month_data.year,
                        month_index=month_idx
                    ))

    # Log statistics
    if vendor_dict:
        total_instances = sum(len(v_list) for v_list in vendor_dict.values())
        unique_cns = set()
        for v_list in vendor_dict.values():
            for vendor in v_list:
                unique_cns.add(vendor.cn)

        logger.info(f"Created month-segregated vendor dictionary:")
        logger.info(f"  - Unique vendors: {len(unique_cns)}")
        logger.info(f"  - Total vendor instances: {total_instances}")
        logger.info(f"  - Months with vendors: {len(vendor_dict)}")
        for month_key, v_list in sorted(vendor_dict.items()):
            logger.info(f"    {month_key[0]} {month_key[1]}: {len(v_list)} vendors")
    else:
        logger.info(f"No vendors available for bench allocation")

    return vendor_dict, valid_states


def get_month_mappings_from_db(
    core_utils: CoreUtils,
    uploaded_file: str,
    report_month: str,
    report_year: int,
    months_record = None
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
        months_record: Optional pre-loaded ForecastMonthsModel record.
                      If provided, skips database query.

    Returns:
        Dict mapping month_index (1-6) to MonthData(month=name, year=year)

    Raises:
        ValueError: If no month mappings found or month config missing
    """
    from code.logics.db import ForecastMonthsModel
    from code.logics.month_config_utils import get_specific_config

    # Use pre-loaded record if provided, otherwise query database
    if months_record is None:
        # Fallback: Query database (for backward compatibility)
        db_manager = core_utils.get_db_manager(ForecastMonthsModel, limit=1, skip=0)

        with db_manager.SessionLocal() as session:
            months_record = session.query(ForecastMonthsModel).filter(
                ForecastMonthsModel.UploadedFile == uploaded_file
            ).first()

            if not months_record:
                raise ValueError(f"No month mappings found for file: {uploaded_file}")

        logger.debug(f"Queried ForecastMonthsModel from database for file: {uploaded_file}")
    else:
        logger.debug(f"Using pre-loaded ForecastMonthsModel record for file: {uploaded_file}")

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
        call_type_id=row['call_type_id'],
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
    core_utils: CoreUtils,
    uploaded_file: Optional[str] = None,
    months_record = None
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
        uploaded_file: Optional pre-loaded uploaded file name.
                      If provided along with months_record, skips extraction from forecast_records.
        months_record: Optional pre-loaded ForecastMonthsModel record.
                      If provided along with uploaded_file, skips database query.

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
        ForecastDataNotFoundException: If no forecast data found
    """
    from code.logics.exceptions import ForecastDataNotFoundException

    db_manager = core_utils.get_db_manager(ForecastModel, limit=None, skip=0, select_columns=None)

    with db_manager.SessionLocal() as session:
        forecast_records = session.query(ForecastModel).filter(
            ForecastModel.Month == month,
            ForecastModel.Year == year
        ).all()

        if not forecast_records:
            raise ForecastDataNotFoundException(month, year)

    # Get month mappings from ForecastMonthsModel (use pre-loaded data if available)
    if uploaded_file is None or months_record is None:
        # Fallback: Extract uploaded_file from forecast_records
        if forecast_records:
            uploaded_file = forecast_records[0].UploadedFile
            logger.debug(f"Extracted uploaded_file from forecast_records: {uploaded_file}")
        else:
            raise ValueError(f"No forecast records found for {month} {year}")

        # Query month mappings (months_record will be None here)
        month_mappings = get_month_mappings_from_db(
            core_utils,
            uploaded_file,
            month,
            year,
            months_record=None  # Will query database
        )
        logger.debug(f"Using ForecastMonthsModel month mappings for file: {uploaded_file}")
    else:
        # Use pre-loaded data (skip database query)
        month_mappings = get_month_mappings_from_db(
            core_utils,
            uploaded_file,
            month,
            year,
            months_record=months_record  # Use pre-loaded record
        )
        logger.debug(f"Using pre-loaded ForecastMonthsModel record for file: {uploaded_file}")

    # Unnormalize to month-level rows
    rows = []
    for record in forecast_records:
        # Parse common fields ONCE per record (outside month loop for 6x performance gain)
        forecast_id = record.id
        call_type_id = record.Centene_Capacity_Plan_Call_Type_ID or ""
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
                'call_type_id': call_type_id,
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
    vendors: List[VendorAllocation],  # Changed from VendorData
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
    vendors: List[VendorAllocation],  # Changed from VendorData
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
    vendors: List[VendorAllocation],  # Changed from VendorData
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

        # Store uploaded file and month data (queried once, reused everywhere)
        self.uploaded_file: str = None
        self.forecast_months_record = None  # Full ForecastMonthsModel record
        self.forecast_months: List[str] = []  # Convenience list [Month1, ..., Month6]

        # Initialize data structures
        self.vendors: Dict[Tuple[str, int], List[VendorAllocation]] = {}  # Month-segregated vendor dictionary
        self.valid_states: set = set()
        self.forecast_df: pd.DataFrame = None
        self.worktype_vocab: List[str] = []

        # Buckets keyed by (platform, location, month, VENDOR_SKILLSET)
        # SIMPLIFIED: Only stores vendor lists (no forecast data)
        self.buckets: Dict[BucketKey, List[VendorAllocation]] = {}

        # Track all allocations (unconsolidated)
        self.allocation_history: List[AllocationData] = []

        # Track allocated vendors by (CN, month) to allow multi-month allocations
        # Maps (vendor_cn, month_name) → forecast_id
        self.allocated_vendors: Dict[Tuple[str, str], int] = {}

        # Consolidation cache - stores computed consolidation result to avoid redundant computation
        # Cache is invalidated when allocation_history changes (after allocate() runs)
        self._consolidated_cache: Optional[Dict[Tuple[int, int], Dict]] = None
        self._cache_valid: bool = False

        # Month configuration cache - stores month configs to minimize DB calls
        # Key: (month_name, year, locality) → config dict
        self._month_config_cache: Dict[Tuple[str, int, str], Dict] = {}

        # Initialize
        from code.logics.exceptions import (
            ExecutionNotFoundException,
            MonthMappingNotFoundException,
            RosterAllotmentNotFoundException,
            EmptyRosterAllotmentException,
            ForecastDataNotFoundException
        )

        logger.info(f"Initializing BenchAllocator for {month} {year} (execution: {execution_id})")

        try:
            self._load_forecast_months_data()  # Load once first
        except ValueError as e:
            # Determine specific error type and raise custom exception
            error_msg = str(e)
            if "Execution" in error_msg and "not found" in error_msg:
                raise ExecutionNotFoundException(execution_id)
            elif "Month mappings not found" in error_msg:
                raise MonthMappingNotFoundException(execution_id, month, year)
            else:
                raise  # Re-raise if unknown

        try:
            self._load_unallocated_vendors()
        except ValueError as e:
            error_msg = str(e)
            if "No roster_allotment report" in error_msg:
                raise RosterAllotmentNotFoundException(execution_id, month, year)
            elif "Empty roster_allotment" in error_msg:
                raise EmptyRosterAllotmentException(execution_id, month, year)
            else:
                raise

        try:
            self._load_and_normalize_forecast_data()
        except ValueError as e:
            error_msg = str(e)
            if "No forecast data found" in error_msg:
                raise ForecastDataNotFoundException(month, year)
            else:
                raise

        self._build_worktype_vocabulary()
        self._initialize_buckets()

        logger.info(f"✓ BenchAllocator initialized:")
        for vendor_month, vendor_list in self.vendors.items():
            logger.info(f"  - Month: {vendor_month[0]}_{vendor_month[1]}, Vendors: {len(vendor_list)}")
        logger.info(f"  - Buckets: {len(self.buckets)}")
        logger.info(f"  - Forecast rows: {len(self.forecast_df)}")

    def _load_forecast_months_data(self):
        """
        Load ForecastMonthsModel data once and store in instance.

        Queries:
        1. AllocationExecutionModel to get uploaded_file
        2. ForecastMonthsModel to get month mappings

        Stores in:
        - self.uploaded_file
        - self.forecast_months_record (full record)
        - self.forecast_months (list of 6 month names)

        Raises:
            ExecutionNotFoundException: When execution record is not found
            MonthMappingNotFoundException: When month mappings are not found
        """
        from code.logics.db import AllocationExecutionModel, ForecastMonthsModel
        from code.logics.exceptions import ExecutionNotFoundException, MonthMappingNotFoundException

        # Query 1: Get uploaded_file from execution
        exec_db = self.core_utils.get_db_manager(
            AllocationExecutionModel,
            limit=None,
            skip=0,
            select_columns=None
        )

        with exec_db.SessionLocal() as session:
            execution = session.query(AllocationExecutionModel).filter(
                AllocationExecutionModel.execution_id == self.execution_id
            ).first()

            if not execution:
                raise ExecutionNotFoundException(self.execution_id)

            self.uploaded_file = execution.ForecastFilename

        # Query 2: Get ForecastMonthsModel record
        month_db = self.core_utils.get_db_manager(
            ForecastMonthsModel,
            limit=None,
            skip=0,
            select_columns=None
        )

        with month_db.SessionLocal() as session:
            month_record = session.query(ForecastMonthsModel).filter(
                ForecastMonthsModel.UploadedFile == self.uploaded_file
            ).first()

            if not month_record:
                raise MonthMappingNotFoundException(self.execution_id, self.month, self.year)

            # Store full record for get_month_mappings_from_db
            self.forecast_months_record = month_record

            # Extract month list for get_unallocated_vendors_with_states
            self.forecast_months = [
                month_record.Month1,
                month_record.Month2,
                month_record.Month3,
                month_record.Month4,
                month_record.Month5,
                month_record.Month6
            ]

        logger.info(f"✓ Loaded forecast months data for file: {self.uploaded_file}")
        logger.info(f"  Months: {self.forecast_months}")

    def _load_unallocated_vendors(self):
        """Load unallocated vendors from roster_allotment report as month-segregated dictionary."""
        self.vendors, self.valid_states = get_unallocated_vendors_with_states(
            self.execution_id,
            self.month,
            self.year,
            self.core_utils,
            forecast_months=self.forecast_months
        )

        # Log dictionary statistics
        if self.vendors:
            total_vendor_instances = sum(len(v_list) for v_list in self.vendors.values())
            unique_cns = set()
            for v_list in self.vendors.values():
                for vendor in v_list:
                    unique_cns.add(vendor.cn)

            logger.info(f"Loaded {len(unique_cns)} unique vendors across {len(self.vendors)} months")
            logger.info(f"Total vendor instances: {total_vendor_instances}")
            logger.info(f"Valid states: {sorted(self.valid_states)}")
        else:
            logger.info(f"No unallocated vendors found")
            logger.info(f"Valid states: {sorted(self.valid_states)}")

    def _load_and_normalize_forecast_data(self):
        """Load ForecastModel and normalize Month1-Month6 to individual rows."""
        self.forecast_df = normalize_forecast_data(
            self.month,
            self.year,
            self.core_utils,
            uploaded_file=self.uploaded_file,
            months_record=self.forecast_months_record
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

        CRITICAL FIX: Uses month-segregated vendor dictionary where vendors only appear
        in months where they're actually unallocated. Creates buckets ONLY for months
        where vendors are available (no wasted iterations).

        State-based bucketing with empty set handling:
        - Vendors with US state codes → state_set = frozenset({'FL', 'GA', ...})
        - Vendors with N/A only → state_set = frozenset() (empty)
        """
        buckets = {}

        logger.info(f"Creating buckets from month-segregated vendor dictionary...")

        # Iterate through month-segregated vendor dictionary
        # Only creates buckets for months where vendors are actually available
        for (month_name, month_year), vendor_list in self.vendors.items():
            logger.info(f"Processing {len(vendor_list)} vendors for {month_name} {month_year}...")

            for vendor in vendor_list:
                # Normalize platform/location
                platform_norm = vendor.platform.strip().split()[0].upper() if vendor.platform else ''
                location_norm = normalize_locality(vendor.location)

                # Parse vendor's full skillset
                skillset = parse_vendor_skills(vendor.skills, self.worktype_vocab)

                if not skillset:
                    logger.debug(f"Skipping vendor {vendor.cn} - no recognized skills")
                    continue

                # Extract vendor's state_set (excluding N/A for specific states)
                vendor_state_set = frozenset(
                    state for state in vendor.state_list
                    if state != 'N/A'
                )
                if not vendor_state_set:
                    vendor_state_set = frozenset()  # Empty set for N/A-only vendors

                # Store normalized fields in vendor (mutate in place)
                vendor.platform_norm = platform_norm
                vendor.location_norm = location_norm
                vendor.skillset = skillset

                # Create bucket key for THIS specific month ONLY
                # Uses vendor.month_name (not iterating all unique_months)
                bucket_key = (platform_norm, location_norm, vendor.month_name, vendor_state_set, skillset)

                if bucket_key not in buckets:
                    buckets[bucket_key] = []

                # Add vendor to bucket (avoid duplicates by CN)
                if vendor not in buckets[bucket_key]:
                    buckets[bucket_key].append(vendor)

        self.buckets = buckets

        logger.info(f"✓ Initialized {len(self.buckets)} buckets (month-specific only)")

        # Log vendor distribution for debugging
        total_vendor_instances = sum(len(v_list) for v_list in buckets.values())
        logger.info(f"  Total vendor instances in buckets: {total_vendor_instances}")

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

        # PHASE 2: Compute totals and update forecast row capacity based on new FTE
        for key, data in consolidated.items():
            total_vendors = len(data['vendors'])

            # Total FTE change = count of vendors (each vendor = 1 FTE)
            data['total_fte_change'] = total_vendors

            # Calculate capacity change for the added vendors
            data['total_capacity_change'] = self._calculate_capacity_for_fte(
                data['forecast_row'],
                total_vendors  # All changed vendors at once
            )

            # CRITICAL UPDATE: Recalculate total capacity based on updated FTE_Avail
            # This ensures forecast_row.capacity reflects the TOTAL capacity with new FTE
            data['forecast_row'].capacity = self._calculate_capacity_for_fte(
                data['forecast_row'],
                data['forecast_row'].fte_avail  # Use current FTE_Avail (already updated during allocation)
            )

        # Cache the result for subsequent calls
        self._consolidated_cache = consolidated
        self._cache_valid = True

        logger.info(f"✓ Consolidated {len(self.allocation_history)} allocations into {len(consolidated)} unique forecast rows (cached)")
        logger.debug(f"Month config cache size: {len(self._month_config_cache)} entries")

        return consolidated

    def _calculate_capacity_for_fte(
        self,
        forecast_row: ForecastRowDict,
        fte_count: int
    ) -> int:
        """
        Calculate capacity for given FTE count using month configuration.

        Formula: capacity = fte_count × working_days × work_hours × (1 - shrinkage) × target_cph

        Uses cached month configurations to minimize database calls.
        Uses centralized calculation utility for consistency across the application.
        """
        from code.logics.capacity_calculations import calculate_capacity

        # Create cache key (month_name, year, locality)
        cache_key = (forecast_row.month_name, forecast_row.month_year, forecast_row.locality_norm)

        # Check cache first
        if cache_key not in self._month_config_cache:
            # Cache miss - fetch from database
            config = get_specific_config(
                forecast_row.month_name,
                forecast_row.month_year,
                forecast_row.locality_norm
            )
            self._month_config_cache[cache_key] = config
            logger.debug(f"Cached month config for {cache_key}")
        else:
            # Cache hit
            config = self._month_config_cache[cache_key]

        # Use centralized calculation utility (returns float, rounded to 2 decimals)
        capacity = calculate_capacity(fte_count, config, forecast_row.target_cph)

        return int(capacity)

    def update_reports(self):
        """
        Update both roster_allotment and bucket_after_allocation reports.

        Should be called after allocation is complete.
        """
        from code.logics.allocation_reports import (
            AllocationReportManager,
            ReportType
        )

        logger.info("Updating allocation reports with bench allocation results...")

        report_manager = AllocationReportManager(self.core_utils)

        # Update roster allotment report
        roster_df = self._generate_bench_roster_allotment()
        if roster_df is not None:
            report_manager.save_report(
                df=roster_df,
                report_type=ReportType.BENCH_ROSTER_ALLOTMENT,
                execution_id=self.execution_id,
                month=self.month,
                year=self.year,
                created_by='bench_allocation',
                upsert=True
            )

        # Update bucket after allocation report
        bucket_df = self._generate_buckets_after_allocation()
        if bucket_df is not None:
            report_manager.save_report(
                df=bucket_df,
                report_type=ReportType.BENCH_BUCKET_AFTER_ALLOCATION,
                execution_id=self.execution_id,
                month=self.month,
                year=self.year,
                created_by='bench_allocation',
                upsert=True
            )

        logger.info("✓ Report updates completed successfully")

        # Populate FTE allocation mapping table for LLM queries
        try:
            from code.logics.fte_allocation_mapping import populate_fte_mapping_from_bench
            consolidated = self.consolidate_changes()
            fte_mapping_count = populate_fte_mapping_from_bench(
                execution_id=self.execution_id,
                month=self.month,
                year=self.year,
                consolidated_changes=consolidated,
                core_utils=self.core_utils
            )
            logger.info(f"✓ Populated {fte_mapping_count} FTE allocation mappings (bench)")
        except Exception as e:
            logger.warning(f"Failed to populate FTE allocation mappings (bench): {e}")

    def _generate_bench_roster_allotment(self) -> Optional[pd.DataFrame]:
        """
        Generate bench_roster_allotment DataFrame based on original roster with bench allocation results.

        Returns DataFrame with:
        1. Status column: 'Not Allocated' → 'Allocated (Bench)' for allocated vendors
        2. Month columns: 'Not Allocated' → 'Main LOB | State | Case Type' for allocated vendors

        Optimizations:
        - Uses CN as index for O(1) lookups instead of O(n) boolean masking
        - Pre-validates month columns to avoid repeated checks
        - Batches status updates using vectorized operations

        Returns:
            DataFrame with updated bench allocations, or None if no allocations or error
        """
        from code.logics.allocation_reports import ReportType

        consolidated = self.consolidate_changes()

        # Group allocations by vendor: CN → [(month, LOB, state, case_type), ...]
        vendor_allocations: Dict[str, List[Tuple[str, str, str, str]]] = {}

        for (forecast_id, month_index), change_data in consolidated.items():
            forecast_row = change_data['forecast_row']
            vendors = change_data['vendors']

            # Use pre-parsed fields
            lob_name = forecast_row.main_lob
            state = forecast_row.state
            case_type = forecast_row.case_type
            month_name = forecast_row.month_name

            # Record allocation for each vendor
            for vendor in vendors:
                if vendor.cn not in vendor_allocations:
                    vendor_allocations[vendor.cn] = []
                vendor_allocations[vendor.cn].append((month_name, lob_name, state, case_type))

        if not vendor_allocations:
            logger.info("No vendor allocations to include in bench_roster_allotment report")
            return None

        db_manager = self.core_utils.get_db_manager(
            AllocationReportsModel,
            limit=None,
            skip=0,
            select_columns=None
        )

        try:
            with db_manager.SessionLocal() as session:
                # Fetch the original roster_allotment report (read-only)
                original_report = session.query(AllocationReportsModel).filter(
                    AllocationReportsModel.execution_id == self.execution_id,
                    AllocationReportsModel.ReportType == ReportType.ROSTER_ALLOTMENT.value
                ).first()

                if not original_report:
                    logger.warning(f"Original roster_allotment report not found for execution {self.execution_id}")
                    return None

                # Parse JSON string to DataFrame (make a copy)
                report_json = original_report.ReportData
                df = pd.read_json(StringIO(report_json))

                logger.info(f"Loaded roster_allotment DataFrame: {len(df)} vendors, {len(df.columns)} columns")

                # Optimization: Set CN as index for O(1) lookups
                if 'CN' not in df.columns:
                    logger.error("CN column not found in roster_allotment DataFrame")
                    return None

                # Set CN as index (drop=False keeps CN as a column too)
                df_indexed = df.set_index('CN', drop=False)

                # Pre-validate which month columns exist (check each unique month only once)
                # Extract unique months from all allocations
                unique_months = set()
                for allocations in vendor_allocations.values():
                    for month_name, _, _, _ in allocations:
                        unique_months.add(month_name)

                # Check column existence for each unique month once
                available_months = set()
                for month_name in unique_months:
                    month_col_lob = f"{month_name}_LOB"
                    month_col_state = f"{month_name}_State"
                    month_col_case = f"{month_name}_Worktype"

                    if all(col in df_indexed.columns for col in [month_col_lob, month_col_state, month_col_case]):
                        available_months.add(month_name)
                    else:
                        logger.warning(f"Month columns for {month_name} not found in DataFrame")

                # Batch update: Collect all CNs to update Status
                allocated_cns = list(vendor_allocations.keys())
                valid_cns = [cn for cn in allocated_cns if cn in df_indexed.index]
                missing_cns = set(allocated_cns) - set(valid_cns)

                if missing_cns:
                    logger.warning(f"{len(missing_cns)} vendor CNs not found in roster_allotment report: {missing_cns}")

                # Vectorized update: Update Status for all allocated vendors at once
                if valid_cns:
                    df_indexed.loc[valid_cns, 'Status'] = 'Allocated (Bench)'

                # Update month columns for each vendor
                updated_count = 0
                for cn in valid_cns:
                    allocations = vendor_allocations[cn]

                    for month_name, lob_name, state, case_type in allocations:
                        # Skip if month columns don't exist
                        if month_name not in available_months:
                            continue

                        # Month column format: "April_LOB", "April_State", "April_Worktype"
                        month_col_lob = f"{month_name}_LOB"
                        month_col_state = f"{month_name}_State"
                        month_col_case = f"{month_name}_Worktype"

                        # Update all three columns for this month
                        df_indexed.loc[cn, month_col_lob] = lob_name
                        df_indexed.loc[cn, month_col_state] = state
                        df_indexed.loc[cn, month_col_case] = case_type
                        updated_count += 1

                logger.info(f"Updated {len(valid_cns)} vendors ({updated_count} month allocations) in bench roster DataFrame")

                # Reset index to original format
                df_updated = df_indexed.reset_index(drop=True)

                return df_updated

        except Exception as e:
            logger.error(f"Error generating bench_roster_allotment DataFrame: {e}", exc_info=True)
            return None

    def _generate_buckets_after_allocation(self) -> pd.DataFrame:
        """
        Generate bucket allocation data after bench allocation.

        Returns DataFrame showing allocated vs unallocated vendors per bucket.
        Each row represents one bucket with vendor allocation statistics.
        """
        bucket_rows = []

        # CRITICAL: Buckets are static lookups NOT updated during allocation
        # Use self.allocated_vendors dict to check allocation status per (CN, month)
        # Build a set of allocated (CN, month) tuples for O(1) lookup
        allocated_set = set(self.allocated_vendors.keys())
        # allocated_set contains tuples: (vendor_cn, month_name)

        # Iterate over buckets (sorted for deterministic output)
        for bucket_key, vendors in sorted(self.buckets.items()):
            # Unpack bucket key (5 elements in bench allocation)
            platform, location, month_name, state_set, skillset = bucket_key

            # Format skills: frozenset -> sorted string with ' + ' delimiter
            skills_str = ' + '.join(sorted(skillset)) if skillset else ''

            # Collect unique states from ALL vendors in bucket
            all_states = set()
            for vendor in vendors:
                all_states.update(vendor.state_list)

            # Remove 'N/A' if other specific states exist
            if len(all_states) > 1 and 'N/A' in all_states:
                all_states.discard('N/A')

            states_str = ', '.join(sorted(all_states)) if all_states else 'N/A'

            # Count allocated vs unallocated vendors for THIS MONTH
            # Check allocation status using (vendor.cn, month_name) in allocated_set
            allocated_count = 0
            unallocated_count = 0
            unallocated_cns = []

            for vendor in vendors:
                allocation_key = (vendor.cn, month_name)
                if allocation_key in allocated_set:
                    allocated_count += 1
                else:
                    unallocated_count += 1
                    unallocated_cns.append(vendor.cn)

            unallocated_vendors_str = ', '.join(unallocated_cns) if unallocated_cns else ''

            bucket_rows.append({
                'Platform': platform,
                'Location': location,
                'Month': month_name,
                'States': states_str,
                'Skills': skills_str,
                'allocated_vendor_count': allocated_count,
                'unallocated_vendor_count': unallocated_count,
                'Unallocated Vendors': unallocated_vendors_str
            })

        # Create DataFrame
        df = pd.DataFrame(bucket_rows)

        logger.info(f"Generated buckets_after_allocation data: {len(df)} buckets")
        if len(df) > 0:
            logger.info(f"  - Total allocated: {df['allocated_vendor_count'].sum()}")
            logger.info(f"  - Total unallocated: {df['unallocated_vendor_count'].sum()}")

        return df

    def export_buckets_before_allocation(self, output_path: str):
        """
        Export bucket data BEFORE allocation to Excel.

        Each row represents a bucket with:
        - Platform: Normalized platform (e.g., "AMISYS", "FACETS")
        - Location: Normalized location (e.g., "Domestic", "Global")
        - Month: Month name (e.g., "April")
        - States: Comma-separated state codes or "N/A"
        - Skills: Comma-separated skillset
        - Vendor_Count: Number of vendors in bucket
        - Vendor_CNs: All vendor CN values concatenated as single string (comma-separated)
        - Vendor_Names: All vendor names (FirstName LastName) concatenated (comma-separated)

        Args:
            output_path: Path where Excel file will be saved
        """
        bucket_rows = []

        # Iterate through all buckets
        for bucket_key, vendors in self.buckets.items():
            platform, location, month_name, state_set, skillset = bucket_key

            # Format states (empty set → "N/A", otherwise comma-separated)
            states_str = ', '.join(sorted(state_set)) if state_set else 'N/A'

            # Format skills (comma-separated)
            skills_str = ', '.join(sorted(skillset))

            # Concatenate vendor CNs
            vendor_cns = ', '.join([vendor.cn for vendor in vendors])

            # Concatenate vendor names (FirstName LastName)
            vendor_names = ', '.join([f"{vendor.first_name} {vendor.last_name}" for vendor in vendors])

            bucket_rows.append({
                'Platform': platform,
                'Location': location,
                'Month': month_name,
                'States': states_str,
                'Skills': skills_str,
                'Vendor_Count': len(vendors),
                'Vendor_CNs': vendor_cns,
                'Vendor_Names': vendor_names
            })

        # Create DataFrame
        df = pd.DataFrame(bucket_rows)

        # Sort by Platform, Location, Month, Skills for readability
        df = df.sort_values(['Platform', 'Location', 'Month', 'Skills'], ignore_index=True)

        # Export to Excel
        df.to_excel(output_path, index=False, sheet_name='Buckets_Before_Allocation')

        logger.info(f"Exported {len(bucket_rows)} buckets to {output_path}")

    def export_consolidated_allocations_to_excel(self, output_path: str):
        """
        Export consolidated allocation changes to an Excel file.

        Each row in the Excel file represents a unique forecast row that was modified
        by the bench allocation process.

        Columns include:
        - Forecast ID, Main LOB, State, Case Type, Month, Year
        - FTE Required, FTE Avail (Original), FTE Avail (After Bench Alloc)
        - Capacity (Original), Capacity (After Bench Alloc)
        - Gap Fill Count, Excess Allocation Count, Total FTE Change,
        - Total Capacity Change, Allocated Vendors (CNs)

        Args:
            output_path: Path where the Excel file will be saved.
        """
        consolidated = self.consolidate_changes()

        if not consolidated:
            logger.info(f"No consolidated changes to export to {output_path}")
            # Create an empty Excel file with headers if no data
            columns = [
                'Forecast ID', 'Main LOB', 'State', 'Case Type', 'Month', 'Year',
                'FTE Required', 'FTE Avail (Original)', 'FTE Avail (After Bench Alloc)',
                'Capacity (Original)', 'Capacity (After Bench Alloc)',
                'Gap Fill Count', 'Excess Allocation Count', 'Total FTE Change',
                'Total Capacity Change', 'Allocated Vendors (CNs)'
            ]
            pd.DataFrame(columns=columns).to_excel(output_path, index=False, sheet_name='Consolidated_Allocations')
            return

        export_data = []
        for (forecast_id, month_index), change_data in consolidated.items():
            forecast_row = change_data['forecast_row']
            vendors = change_data['vendors']

            export_data.append({
                'Forecast ID': forecast_row.forecast_id,
                'Main LOB': forecast_row.main_lob,
                'State': forecast_row.state,
                'Case Type': forecast_row.case_type,
                'Month': forecast_row.month_name,
                'Year': forecast_row.month_year,
                'FTE Required': forecast_row.fte_required,
                'FTE Avail (Original)': forecast_row.fte_avail_original,
                'FTE Avail (After Bench Alloc)': forecast_row.fte_avail,
                'Capacity (Original)': forecast_row.capacity_original,
                'Capacity (After Bench Alloc)': forecast_row.capacity,
                'Gap Fill Count': change_data['gap_fill_count'],
                'Excess Allocation Count': change_data['excess_count'],
                'Total FTE Change': change_data['total_fte_change'],
                'Total Capacity Change': change_data['total_capacity_change'],
                'Allocated Vendors (CNs)': ', '.join([v.cn for v in vendors])
            })

        df = pd.DataFrame(export_data)

        # Sort for readability
        df = df.sort_values([
            'Main LOB', 'State', 'Case Type', 'Year', 'Month'
        ], ignore_index=True)

        df.to_excel(output_path, index=False, sheet_name='Consolidated_Allocations')

        logger.info(f"Exported {len(export_data)} consolidated allocations to {output_path}")

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

        output_path = os.path.join(BASE_DIR, "logics", "buckets_before_allocation.xlsx")
        allocator.export_buckets_before_allocation(output_path)
        logger.info(f"Exported buckets before allocation to {output_path}")
        # Check if there are vendors to allocate
        if not allocator.vendors:
            logger.info(f"No unallocated vendors found for {month} {year}")
            return AllocationResult(
                success=True,
                month=month,
                year=year,
                total_bench_allocated=0,
                gaps_filled=0,
                excess_distributed=0,
                rows_modified=0,
                allocations=[],
                info_message="No bench capacity available to allocate (all vendors already allocated)"
            )

        logger.info(f"✓ Found {len(allocator.vendors)} unallocated vendors")
        logger.info(f"✓ Created {len(allocator.buckets)} buckets")

        # Step 3: Run allocation
        total_allocated = allocator.allocate()

        logger.info(f"✓ Total allocations: {total_allocated}")

        # Step 4: Consolidate changes
        consolidated = allocator.consolidate_changes()
        output_path = os.path.join(BASE_DIR, "logics", "consolidated_data.xlsx")
        allocator.export_consolidated_allocations_to_excel(output_path)

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
                call_type_id=forecast_row.call_type_id,
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

            # Vendors are already VendorAllocation instances - no conversion needed
            vendor_allocations = vendors

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
        from code.logics.exceptions import EditViewException

        # Re-raise custom exceptions to preserve structure
        if isinstance(e, EditViewException):
            raise

        # Log and return structured error for unexpected exceptions
        logger.error(f"Unexpected error during bench allocation: {e}", exc_info=True)
        return AllocationResult(
            success=False,
            month=month,
            year=year,
            total_bench_allocated=0,
            gaps_filled=0,
            excess_distributed=0,
            rows_modified=0,
            allocations=[],
            error=f"Allocation failed: {type(e).__name__}: {str(e)}",
            recommendation="Contact system administrator if this persists."
        )

