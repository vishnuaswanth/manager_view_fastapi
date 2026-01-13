"""
Data transformation functions for bench allocation preview and history logging.

Transforms AllocationResult objects to API response format and prepares
field-level change data for history tracking.
"""

import logging
from typing import Dict, List, Optional, Union
from dataclasses import dataclass
from pydantic import BaseModel, Field
from code.logics.core_utils import CoreUtils
from code.logics.edit_view_utils import (
    get_months_dict,
    get_ordered_month_labels,
    parse_field_path
)
from code.logics.bench_allocation import AllocationResult

logger = logging.getLogger(__name__)


# ============================================================================
# TYPE-SAFE DATA STRUCTURES
# ============================================================================

@dataclass
class HistoryChangeData:
    """
    Type-safe structure for history change records.

    Provides strong typing for field-level changes tracked in history logging.
    Used to ensure data consistency and catch type errors at development time.

    Attributes:
        main_lob: Main Line of Business identifier
        state: State code (2-letter)
        case_type: Case type description
        case_id: Business case identifier (Centene_Capacity_Plan_Call_Type_ID)
        field_name: Field path in DOT notation (e.g., "Jun-25.fte_avail" or "target_cph")
        old_value: Previous value before change (can be None for new records)
        new_value: Current value after change
        delta: Change amount (new_value - old_value)
        month_label: Month label if field is month-specific (e.g., "Jun-25"), None otherwise

    Example:
        >>> change = HistoryChangeData(
        ...     main_lob="Amisys Medicaid DOMESTIC",
        ...     state="TX",
        ...     case_type="Claims Processing",
        ...     case_id="CL-001",
        ...     field_name="Jun-25.fte_avail",
        ...     old_value=20,
        ...     new_value=25,
        ...     delta=5,
        ...     month_label="Jun-25"
        ... )
        >>> change_dict = change.to_dict()
    """
    main_lob: str
    state: str
    case_type: str
    case_id: str
    field_name: str
    old_value: Union[int, float, str, None]
    new_value: Union[int, float, str]
    delta: Union[int, float]
    month_label: Optional[str] = None

    def to_dict(self) -> Dict:
        """
        Convert to dict for database insertion.

        Returns:
            Dict with all fields ready for HistoryChangeModel insertion
        """
        return {
            "main_lob": self.main_lob,
            "state": self.state,
            "case_type": self.case_type,
            "case_id": self.case_id,
            "field_name": self.field_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "delta": self.delta,
            "month_label": self.month_label
        }


# ============================================================================
# PYDANTIC RESPONSE MODELS
# ============================================================================

class MonthDataResponse(BaseModel):
    """Month-specific data with before/after values"""
    forecast: int = Field(ge=0, description="Client forecast value")
    fte_req: int = Field(ge=0, description="FTE required")
    fte_avail: int = Field(ge=0, description="FTE available after allocation")
    capacity: int = Field(ge=0, description="Capacity after allocation")
    forecast_change: int = Field(default=0, description="Change in forecast (typically 0 for bench allocation)")
    fte_req_change: int = Field(default=0, description="Change in FTE required (typically 0)")
    fte_avail_change: int = Field(description="Change in FTE available")
    capacity_change: int = Field(description="Change in capacity")

    class Config:
        extra = "forbid"


class ModifiedRecordResponse(BaseModel):
    """Single modified forecast record with month data"""
    main_lob: str = Field(min_length=1, description="Main LOB identifier")
    state: str = Field(min_length=1, description="State code")
    case_type: str = Field(min_length=1, description="Case type description")
    case_id: str = Field(min_length=1, description="Business case identifier (Centene_Capacity_Plan_Call_Type_ID, used for updates)")
    target_cph: int = Field(gt=0, description="Target cases per hour")
    target_cph_change: int = Field(default=0, description="Change in target CPH (typically 0)")
    modified_fields: List[str] = Field(
        default_factory=list,
        description="List of modified field paths (e.g., 'Jun-25.fte_avail')"
    )
    months: Dict[str, MonthDataResponse] = Field(
        default_factory=dict,
        description="Month-specific data keyed by month label (e.g., 'Jun-25')"
    )

    class Config:
        extra = "forbid"


class SummaryResponse(BaseModel):
    """Summary of total changes across all records"""
    total_fte_change: int = Field(ge=0, description="Total absolute FTE changes")
    total_capacity_change: int = Field(ge=0, description="Total absolute capacity changes")

    class Config:
        extra = "forbid"


class PreviewResponse(BaseModel):
    """Complete preview response for bench allocation"""
    success: bool = Field(description="Operation success status")
    months: Dict[str, str] = Field(description="Month index mapping (e.g., {'month1': 'Jun-25'})")
    month: str = Field(min_length=1, description="Report month name")
    year: int = Field(gt=2000, description="Report year")
    modified_records: List[ModifiedRecordResponse] = Field(
        default_factory=list,
        description="List of records with modifications"
    )
    total_modified: int = Field(ge=0, description="Total number of modified records")
    summary: SummaryResponse = Field(description="Aggregated summary data")
    message: Optional[str] = Field(default=None, description="Optional status message")

    class Config:
        extra = "forbid"


# ============================================================================
# TRANSFORMATION FUNCTIONS
# ============================================================================

def transform_allocation_result_to_preview(
    allocation_result: AllocationResult,
    month: str,
    year: int,
    core_utils: CoreUtils
) -> PreviewResponse:
    """
    Transform AllocationResult to API preview response format.

    CRITICAL: allocation_result.allocations is a FLAT list where each entry
    represents ONE month for ONE forecast row. Must group by forecast identifier.

    Args:
        allocation_result: AllocationResult dataclass from allocate_bench_for_month().
                          Contains success status, month/year, and list of AllocationRecord
                          objects with forecast_row (ForecastRowData) and vendor details.
        month: Report month name (e.g., "March")
        year: Report year (e.g., 2025)
        core_utils: CoreUtils instance for database access to query month mappings

    Returns:
        PreviewResponse: Pydantic model containing:
            - success: Operation status
            - months: Month index mapping dict
            - month/year: Report period
            - modified_records: List of ModifiedRecordResponse with:
                - case_id: Business identifier (Centene_Capacity_Plan_Call_Type_ID) used for updates
                - Month-specific FTE and capacity changes
            - total_modified: Count of modified records
            - summary: SummaryResponse with aggregated FTE and capacity changes
            - message: Optional status message

    Raises:
        ValueError: If allocation_result is invalid, missing required attributes,
                   or month mappings not found in database
        AttributeError: If allocation records have invalid structure or missing
                       required attributes (forecast_row, fte_change, etc.)

    Example:
        >>> result = allocate_bench_for_month(month="March", year=2025, ...)
        >>> preview = transform_allocation_result_to_preview(result, "March", 2025, core_utils)
        >>> print(preview.total_modified)
        15
        >>> print(preview.summary.total_fte_change)
        23
    """
    try:
        # Input validation
        if not allocation_result:
            raise ValueError("allocation_result cannot be None")

        if not hasattr(allocation_result, 'allocations'):
            raise ValueError("allocation_result missing 'allocations' attribute")

        if not allocation_result.allocations:
            raise ValueError("allocation_result.allocations is empty")

        if not month or not isinstance(month, str):
            raise ValueError(f"Invalid month parameter: {month}")

        if not year or not isinstance(year, int):
            raise ValueError(f"Invalid year parameter: {year}")

        if not core_utils:
            raise ValueError("core_utils cannot be None")

        # Step 1: Get month mappings from database
        months_dict = get_months_dict(month, year, core_utils)

        if not months_dict:
            raise ValueError(f"No month mappings found for {month} {year}")

    except Exception as e:
        logger.error(f"Validation error in transform_allocation_result_to_preview: {e}", exc_info=True)
        raise

    # Step 2: Group allocations by forecast_id
    grouped_allocations = {}

    try:
        for i, allocation_record in enumerate(allocation_result.allocations):
            # Validate allocation record structure
            if not hasattr(allocation_record, 'forecast_row'):
                raise AttributeError(
                    f"Allocation record at index {i} missing 'forecast_row' attribute"
                )

            forecast_row = allocation_record.forecast_row

            if not hasattr(forecast_row, 'forecast_id'):
                raise AttributeError(
                    f"Forecast row at index {i} missing 'forecast_id' attribute"
                )

            forecast_id = forecast_row.forecast_id

            if forecast_id not in grouped_allocations:
                grouped_allocations[forecast_id] = []

            grouped_allocations[forecast_id].append(allocation_record)

    except AttributeError as e:
        logger.error(f"Invalid allocation record structure: {e}", exc_info=True)
        raise ValueError(f"Invalid allocation data structure: {e}")
    except Exception as e:
        logger.error(f"Error grouping allocations: {e}", exc_info=True)
        raise

    # Step 3: Transform each group into preview format
    modified_records = []
    total_fte_change = 0
    total_capacity_change = 0

    try:
        for forecast_id, allocation_group in grouped_allocations.items():
            if not allocation_group:
                logger.warning(f"Empty allocation group for forecast_id {forecast_id}, skipping")
                continue

            # Get common attributes from first record (same for all months)
            first_record = allocation_group[0]

            if not hasattr(first_record, 'forecast_row'):
                raise AttributeError(f"First record for forecast_id {forecast_id} missing 'forecast_row'")

            first_row = first_record.forecast_row

            # Validate required attributes
            required_attrs = ['main_lob', 'state', 'case_type', 'target_cph']
            for attr in required_attrs:
                if not hasattr(first_row, attr):
                    raise AttributeError(
                        f"Forecast row for forecast_id {forecast_id} missing '{attr}' attribute"
                    )

            # Build record with Pydantic models
            month_data_dict = {}
            modified_fields = []

            # Initialize all 6 months (some may not have allocation records)
            for month_idx, month_label in months_dict.items():
                month_data_dict[month_label] = MonthDataResponse(
                    forecast=0,
                    fte_req=0,
                    fte_avail=0,
                    capacity=0,
                    forecast_change=0,
                    fte_req_change=0,
                    fte_avail_change=0,
                    capacity_change=0
                )

            # Populate month data from allocation records
            for allocation_record in allocation_group:
                if not hasattr(allocation_record, 'forecast_row'):
                    raise AttributeError(
                        f"Allocation record for forecast_id {forecast_id} missing 'forecast_row'"
                    )

                forecast_row = allocation_record.forecast_row

                # Validate required attributes for month data
                if not hasattr(forecast_row, 'month_index'):
                    raise AttributeError(
                        f"Forecast row for forecast_id {forecast_id} missing 'month_index'"
                    )

                # Map month_index (1-6) to month_label ("Jun-25", etc.)
                month_key = f"month{forecast_row.month_index}"

                if month_key not in months_dict:
                    raise KeyError(
                        f"Month key '{month_key}' not found in months_dict for forecast_id {forecast_id}"
                    )

                month_label = months_dict[month_key]

                # Validate required attributes for data population
                required_attrs = ['forecast', 'fte_required', 'fte_avail', 'capacity']
                for attr in required_attrs:
                    if not hasattr(forecast_row, attr):
                        raise AttributeError(
                            f"Forecast row for forecast_id {forecast_id} missing '{attr}' attribute"
                        )

                # Validate allocation_record attributes
                if not hasattr(allocation_record, 'fte_change') or not hasattr(allocation_record, 'capacity_change'):
                    raise AttributeError(
                        f"Allocation record for forecast_id {forecast_id} missing change attributes"
                    )

                # Populate month data using forecast_row attributes
                month_data_dict[month_label] = MonthDataResponse(
                    forecast=forecast_row.forecast,
                    fte_req=forecast_row.fte_required,
                    fte_avail=forecast_row.fte_avail,
                    capacity=forecast_row.capacity,
                    forecast_change=0,  # Forecast doesn't change in bench allocation
                    fte_req_change=0,   # FTE req doesn't change
                    fte_avail_change=allocation_record.fte_change,
                    capacity_change=allocation_record.capacity_change
                )

                # Track modified fields
                if allocation_record.fte_change != 0:
                    modified_fields.append(f"{month_label}.fte_avail")
                    total_fte_change += abs(allocation_record.fte_change)
                if allocation_record.capacity_change != 0:
                    modified_fields.append(f"{month_label}.capacity")
                    total_capacity_change += abs(allocation_record.capacity_change)

            # Only include records with changes
            if modified_fields:
                record_response = ModifiedRecordResponse(
                    main_lob=first_row.main_lob,
                    state=first_row.state,
                    case_type=first_row.case_type,
                    case_id=first_row.call_type_id,  # Business identifier (used for database updates)
                    target_cph=first_row.target_cph,
                    target_cph_change=0,
                    modified_fields=modified_fields,
                    months=month_data_dict
                )
                modified_records.append(record_response)

    except KeyError as e:
        logger.error(f"Missing required key in data: {e}", exc_info=True)
        raise ValueError(f"Invalid data structure: {e}")
    except AttributeError as e:
        logger.error(f"Missing required attribute: {e}", exc_info=True)
        raise ValueError(f"Invalid allocation record structure: {e}")
    except Exception as e:
        logger.error(f"Error transforming allocation data: {e}", exc_info=True)
        raise

    # Step 4: Build response
    summary = SummaryResponse(
        total_fte_change=total_fte_change,
        total_capacity_change=total_capacity_change
    )

    response = PreviewResponse(
        success=True,
        months=months_dict,
        month=month,
        year=year,
        modified_records=modified_records,
        total_modified=len(modified_records),
        summary=summary,
        message=None
    )

    return response


def _get_month_data(record: Dict, month_label: str) -> Optional[Dict]:
    """
    Extract month data from record, handling both flat and nested structures.

    Supports two formats:
    1. Flat structure (expected): record["Jun-25"] = {...}
    2. Nested structure (actual from preview): record["months"]["Jun-25"] = {...}

    This function enables backward compatibility by accepting both data structures,
    fixing the history records bug where old values showed as 0 and new values
    showed as deltas instead of actual values.

    Args:
        record: Modified record dict from update request
        month_label: Month label (e.g., "Jun-25")

    Returns:
        Month data dict with keys: forecast, fte_req, fte_avail, capacity,
        forecast_change, fte_req_change, fte_avail_change, capacity_change
        Returns None if month data not found

    Example:
        >>> record = {"Jun-25": {"forecast": 1000, "fte_avail": 25, "fte_avail_change": 5}}
        >>> _get_month_data(record, "Jun-25")
        {"forecast": 1000, "fte_avail": 25, "fte_avail_change": 5}

        >>> record = {"months": {"Jun-25": {"forecast": 1000, "fte_avail": 25}}}
        >>> _get_month_data(record, "Jun-25")
        {"forecast": 1000, "fte_avail": 25}
    """
    # Try root level first (flat structure - expected format)
    if month_label in record:
        month_data = record[month_label]
        if isinstance(month_data, dict):
            logger.debug(f"Found month data for '{month_label}' at root level (flat structure)")
            return month_data
        else:
            logger.warning(
                f"Month data for '{month_label}' at root level is not a dict: {type(month_data)}"
            )
            return None

    # Try nested under "months" key (nested structure - actual format from preview)
    if "months" in record:
        months_container = record["months"]
        if isinstance(months_container, dict):
            month_data = months_container.get(month_label)
            if month_data is not None:
                if isinstance(month_data, dict):
                    logger.debug(
                        f"Found month data for '{month_label}' in nested 'months' key (nested structure)"
                    )
                    return month_data
                else:
                    logger.warning(
                        f"Month data for '{month_label}' in 'months' is not a dict: {type(month_data)}"
                    )
                    return None
        else:
            logger.warning(f"'months' key exists but is not a dict: {type(months_container)}")

    # Not found in either location
    logger.debug(f"Month data for '{month_label}' not found in record (checked root and 'months' key)")
    return None


def extract_specific_changes(
    modified_records: List[Dict],
    months_dict: Dict[str, str]
) -> List[Dict]:
    """
    Extract field-level changes from modified records for history logging.

    Args:
        modified_records: List of records from preview/update request.
                         Each record must contain case_id (Centene_Capacity_Plan_Call_Type_ID).
        months_dict: Month index mapping (e.g., {"month1": "Jun-25"})

    Returns:
        List of change dicts ready for HistoryChangeModel

    Raises:
        ValueError: If modified_records or months_dict are invalid
        KeyError: If required keys are missing from records
    """
    # Input validation
    if not isinstance(modified_records, list):
        raise ValueError("modified_records must be a list")

    if not isinstance(months_dict, dict):
        raise ValueError("months_dict must be a dict")

    all_changes = []

    try:
        for i, record in enumerate(modified_records):
            # Validate record structure
            if not isinstance(record, dict):
                raise ValueError(f"Record at index {i} is not a dict")

            # Validate required keys
            required_keys = ["main_lob", "state", "case_type", "case_id"]
            missing_keys = [k for k in required_keys if k not in record]
            if missing_keys:
                raise KeyError(
                    f"Record at index {i} missing required keys: {missing_keys}"
                )

            main_lob = record["main_lob"]
            state = record["state"]
            case_type = record["case_type"]
            case_id = record["case_id"]
            modified_fields = record.get("modified_fields", [])

            if not isinstance(modified_fields, list):
                raise ValueError(f"Record at index {i}: modified_fields must be a list")

            for field_path in modified_fields:
                # Parse field path (DOT notation) using utility function
                month_label, field_name = parse_field_path(field_path)

                if month_label:
                    # Month-specific field: "Jun-25.fte_avail"
                    # Use helper to extract month data (handles both flat and nested structures)
                    month_data = _get_month_data(record, month_label)

                    if not isinstance(month_data, dict):
                        raise ValueError(
                            f"Record at index {i}: month_label '{month_label}' not found or not a dict. "
                            f"Expected either record['{month_label}'] or record['months']['{month_label}']"
                        )

                    # Get old/new values
                    new_value = month_data.get(field_name)
                    delta = month_data.get(f"{field_name}_change", 0)
                    old_value = new_value - delta if isinstance(new_value, (int, float)) else None

                    all_changes.append({
                        "main_lob": main_lob,
                        "state": state,
                        "case_type": case_type,
                        "case_id": case_id,
                        "field_name": field_path,  # Keep DOT notation
                        "old_value": old_value,
                        "new_value": new_value,
                        "delta": delta,
                        "month_label": month_label
                    })
                else:
                    # Month-agnostic field: "target_cph"
                    new_value = record.get(field_path)
                    delta = record.get(f"{field_path}_change", 0)
                    old_value = new_value - delta if isinstance(new_value, (int, float)) else None

                    all_changes.append({
                        "main_lob": main_lob,
                        "state": state,
                        "case_type": case_type,
                        "case_id": case_id,
                        "field_name": field_path,
                        "old_value": old_value,
                        "new_value": new_value,
                        "delta": delta,
                        "month_label": None  # No month context
                    })

    except KeyError as e:
        logger.error(f"Missing required key in modified_records: {e}", exc_info=True)
        raise ValueError(f"Invalid record structure: {e}")
    except ValueError as e:
        logger.error(f"Validation error in extract_specific_changes: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Unexpected error in extract_specific_changes: {e}", exc_info=True)
        raise

    return all_changes


def calculate_summary_data(
    modified_records: List[Dict],
    months_dict: Dict[str, str],
    month: str,
    year: int
) -> Dict:
    """
    Calculate aggregated before/after totals by month.

    Args:
        modified_records: List of modified records
        months_dict: Month index mapping
        month: Report month
        year: Report year

    Returns:
        Summary data dict for HistoryLogModel.SummaryData

    Raises:
        ValueError: If input parameters are invalid
        KeyError: If required keys are missing
    """
    # Input validation
    if not isinstance(modified_records, list):
        raise ValueError("modified_records must be a list")

    if not isinstance(months_dict, dict):
        raise ValueError("months_dict must be a dict")

    if not month or not isinstance(month, str):
        raise ValueError(f"Invalid month parameter: {month}")

    if not year or not isinstance(year, int):
        raise ValueError(f"Invalid year parameter: {year}")

    try:
        # Initialize aggregates per month
        month_totals = {}
        for month_label in get_ordered_month_labels(months_dict):
            month_totals[month_label] = {
                "total_forecast": {"old": 0, "new": 0},
                "total_fte_required": {"old": 0, "new": 0},
                "total_fte_available": {"old": 0, "new": 0},
                "total_capacity": {"old": 0, "new": 0}
            }

    except Exception as e:
        logger.error(f"Error initializing month totals: {e}", exc_info=True)
        raise ValueError(f"Failed to initialize summary data: {e}")

    # Aggregate across all modified records
    try:
        for i, record in enumerate(modified_records):
            if not isinstance(record, dict):
                raise ValueError(f"Record at index {i} is not a dict")

            for month_label in get_ordered_month_labels(months_dict):
                if month_label not in month_totals:
                    logger.warning(f"Month label '{month_label}' not in month_totals, skipping")
                    continue

                month_data = record.get(month_label, {})

                if month_data:
                    if not isinstance(month_data, dict):
                        raise ValueError(
                            f"Record at index {i}: month_data for '{month_label}' is not a dict"
                        )

                    # Forecast (no change expected in most cases)
                    forecast = month_data.get("forecast", 0)
                    forecast_change = month_data.get("forecast_change", 0)
                    month_totals[month_label]["total_forecast"]["new"] += forecast
                    month_totals[month_label]["total_forecast"]["old"] += (forecast - forecast_change)

                    # FTE Required
                    fte_req = month_data.get("fte_req", 0)
                    fte_req_change = month_data.get("fte_req_change", 0)
                    month_totals[month_label]["total_fte_required"]["new"] += fte_req
                    month_totals[month_label]["total_fte_required"]["old"] += (fte_req - fte_req_change)

                    # FTE Available
                    fte_avail = month_data.get("fte_avail", 0)
                    fte_avail_change = month_data.get("fte_avail_change", 0)
                    month_totals[month_label]["total_fte_available"]["new"] += fte_avail
                    month_totals[month_label]["total_fte_available"]["old"] += (fte_avail - fte_avail_change)

                    # Capacity
                    capacity = month_data.get("capacity", 0)
                    capacity_change = month_data.get("capacity_change", 0)
                    month_totals[month_label]["total_capacity"]["new"] += capacity
                    month_totals[month_label]["total_capacity"]["old"] += (capacity - capacity_change)

    except ValueError as e:
        logger.error(f"Validation error in calculate_summary_data: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Error aggregating summary data: {e}", exc_info=True)
        raise

    return {
        "report_month": month,
        "report_year": year,
        "months": get_ordered_month_labels(months_dict),
        "totals": month_totals
    }
