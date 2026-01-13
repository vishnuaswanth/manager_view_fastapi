"""
Shared utility functions for Edit View API implementation.

Provides reusable functions for month mappings, field conversions, validation,
and other common operations to eliminate code duplication across modules.
"""

import logging
from typing import Dict, List, Optional
from code.logics.db import ForecastMonthsModel
from code.logics.core_utils import CoreUtils

logger = logging.getLogger(__name__)


# ============ Month Mapping Utilities ============

def get_months_dict(month: str, year: int, core_utils: CoreUtils) -> Dict[str, str]:
    """
    Get month mappings for a report month/year from ForecastMonthsModel.

    Reads month names from database and constructs formatted labels with years.

    Results are cached with 1 hour TTL since month mappings are static.

    Args:
        month: Report month name (e.g., "April")
        year: Report year (e.g., 2025)
        core_utils: CoreUtils instance for database access

    Returns:
        Dictionary mapping month indices to labels:
        {"month1": "Jun-25", "month2": "Jul-25", ..., "month6": "Nov-25"}

    Raises:
        ValueError: If month mappings not found in database
    """
    from code.cache import month_mappings_cache, generate_month_mappings_cache_key
    from calendar import month_name as cal_month_name, month_abbr as cal_month_abbr
    from datetime import datetime

    # Check cache first
    cache_key = generate_month_mappings_cache_key(month, year)
    cached_result = month_mappings_cache.get(cache_key)

    if cached_result is not None:
        logger.debug(f"[Cache HIT] Month mappings for {month} {year}")
        return cached_result

    logger.debug(f"[Cache MISS] Month mappings for {month} {year}, querying database")

    # Query database
    db_manager = core_utils.get_db_manager(
        ForecastMonthsModel,
        limit=1,
        skip=0,
        select_columns=None
    )

    with db_manager.SessionLocal() as session:
        record = session.query(ForecastMonthsModel).filter(
            ForecastMonthsModel.UploadedFile.contains(f"{month}_{year}")
        ).order_by(
            ForecastMonthsModel.CreatedDateTime.desc()
        ).first()

        if not record:
            raise ValueError(f"Month mappings not found for {month} {year}")

        # Get report month number for year wrapping calculation
        report_month_num = list(cal_month_name).index(month.strip().capitalize())

        # Helper function to construct month label with year
        def construct_month_label(month_name: str) -> str:
            """
            Construct formatted month label (e.g., "Jun-25") from month name.

            Args:
                month_name: Full month name (e.g., "June")

            Returns:
                Formatted label: "Mon-YY" (e.g., "Jun-25")
            """
            # Parse month name to get month number
            forecast_month_num = list(cal_month_name).index(month_name.strip().capitalize())

            # Determine year: if report month > forecast month, year wraps to next year
            # Example: October 2024 report with January forecast → 2025
            forecast_year = year + 1 if report_month_num > forecast_month_num else year

            # Get abbreviated month name (3 letters)
            month_abbr = cal_month_abbr[forecast_month_num]

            # Format as "Mon-YY"
            return f"{month_abbr}-{str(forecast_year)[-2:]}"

        result = {
            "month1": construct_month_label(record.Month1),
            "month2": construct_month_label(record.Month2),
            "month3": construct_month_label(record.Month3),
            "month4": construct_month_label(record.Month4),
            "month5": construct_month_label(record.Month5),
            "month6": construct_month_label(record.Month6),
        }

        # Cache the result
        month_mappings_cache.set(cache_key, result)
        logger.debug(f"[Cache SET] Month mappings for {month} {year}: {result}")

        return result


def get_ordered_month_labels(months_dict: Dict[str, str]) -> List[str]:
    """
    Get month labels in order from months_dict.

    Uses explicit key access to guarantee order, not relying on dict order.

    Args:
        months_dict: Dictionary mapping month indices to labels

    Returns:
        List of month labels in order: ["Jun-25", "Jul-25", ..., "Nov-25"]
    """
    return [
        months_dict["month1"],
        months_dict["month2"],
        months_dict["month3"],
        months_dict["month4"],
        months_dict["month5"],
        months_dict["month6"]
    ]


def reverse_months_dict(months_dict: Dict[str, str]) -> Dict[str, str]:
    """
    Reverse months dict for lookup by month label.

    Args:
        months_dict: Original dict {"month1": "Jun-25", ...}

    Returns:
        Reversed dict {"Jun-25": "month1", ...}
    """
    return {v: k for k, v in months_dict.items()}


def extract_month_suffix_from_index(month_index: str) -> str:
    """
    Extract numeric suffix from month index.

    Args:
        month_index: Month index like "month1", "month2", etc.

    Returns:
        Numeric suffix: "1", "2", etc.

    Examples:
        extract_month_suffix_from_index("month1") -> "1"
        extract_month_suffix_from_index("month6") -> "6"
    """
    return month_index.replace("month", "")


# ============ Field Mapping Utilities ============

def get_month_index_to_attr_map() -> Dict[str, str]:
    """
    Get mapping from month index to ForecastModel attribute prefix.

    Returns:
        Dict mapping month index to attribute prefix:
        {"month1": "Month1", "month2": "Month2", ...}
    """
    return {
        "month1": "Month1",
        "month2": "Month2",
        "month3": "Month3",
        "month4": "Month4",
        "month5": "Month5",
        "month6": "Month6"
    }


def get_forecast_column_name(api_field: str, month_suffix: str) -> Optional[str]:
    """
    Get ForecastModel column name from API field name and month suffix.

    Args:
        api_field: API field name (forecast, fte_req, fte_avail, capacity, target_cph)
        month_suffix: Month suffix ("1", "2", ..., "6")

    Returns:
        ForecastModel column name or None if invalid field

    Examples:
        get_forecast_column_name("forecast", "1") -> "Client_Forecast_Month1"
        get_forecast_column_name("fte_avail", "3") -> "FTE_Avail_Month3"
        get_forecast_column_name("target_cph", "1") -> "Target_CPH"
    """
    if api_field == "target_cph":
        return "Target_CPH"

    field_patterns = {
        "forecast": f"Client_Forecast_Month{month_suffix}",
        "fte_req": f"FTE_Required_Month{month_suffix}",
        "fte_avail": f"FTE_Avail_Month{month_suffix}",
        "capacity": f"Capacity_Month{month_suffix}"
    }
    return field_patterns.get(api_field)


def parse_field_path(field_path: str) -> tuple:
    """
    Parse field path in DOT notation.

    Args:
        field_path: Field path (e.g., "Jun-25.fte_avail" or "target_cph")

    Returns:
        Tuple of (month_label or None, field_name)

    Examples:
        parse_field_path("Jun-25.fte_avail") -> ("Jun-25", "fte_avail")
        parse_field_path("target_cph") -> (None, "target_cph")
    """
    if "." in field_path:
        parts = field_path.split(".", 1)
        return (parts[0], parts[1])
    else:
        return (None, field_path)


def build_field_path(month_label: Optional[str], field_name: str) -> str:
    """
    Build field path in DOT notation.

    Args:
        month_label: Month label (e.g., "Jun-25") or None for month-agnostic fields
        field_name: Field name (e.g., "fte_avail", "target_cph")

    Returns:
        Field path string

    Examples:
        build_field_path("Jun-25", "fte_avail") -> "Jun-25.fte_avail"
        build_field_path(None, "target_cph") -> "target_cph"
    """
    if month_label:
        return f"{month_label}.{field_name}"
    else:
        return field_name


# ============ Validation Utilities ============

def validate_months_dict(months_dict: Dict[str, str]) -> bool:
    """
    Validate months dict structure.

    Args:
        months_dict: Dictionary to validate

    Returns:
        True if valid, False otherwise
    """
    required_keys = ["month1", "month2", "month3", "month4", "month5", "month6"]
    if not all(key in months_dict for key in required_keys):
        return False

    # Validate format: "Mon-YY"
    import re
    pattern = r'^[A-Z][a-z]{2}-\d{2}$'
    return all(re.match(pattern, months_dict[key]) for key in required_keys)


def validate_field_path(field_path: str) -> bool:
    """
    Validate field path format.

    Args:
        field_path: Field path to validate

    Returns:
        True if valid format, False otherwise
    """
    month_label, field_name = parse_field_path(field_path)

    # Valid field names
    valid_fields = ["forecast", "fte_req", "fte_avail", "capacity", "target_cph"]
    if field_name not in valid_fields:
        return False

    # If has month label, validate format
    if month_label:
        import re
        pattern = r'^[A-Z][a-z]{2}-\d{2}$'
        return bool(re.match(pattern, month_label))

    return True


def validate_api_field_name(api_field: str) -> bool:
    """
    Validate API field name.

    Args:
        api_field: Field name to validate

    Returns:
        True if valid, False otherwise
    """
    valid_fields = ["forecast", "fte_req", "fte_avail", "capacity", "target_cph"]
    return api_field in valid_fields


# ============ Record Identifier Utilities ============

def get_record_identifier(record: Dict) -> tuple:
    """
    Get unique identifier tuple for a forecast record.

    Args:
        record: Record dict with main_lob, state, case_type, case_id

    Returns:
        Tuple of (main_lob, state, case_type, case_id)
    """
    return (
        record.get("main_lob", ""),
        record.get("state", ""),
        record.get("case_type", ""),
        record.get("case_id", "")
    )


def format_record_identifier(main_lob: str, state: str, case_type: str, case_id: str) -> str:
    """
    Format record identifier as string for logging.

    Args:
        main_lob: Main LOB
        state: State
        case_type: Case type
        case_id: Case ID

    Returns:
        Formatted identifier string

    Example:
        "Amisys Medicaid DOMESTIC | LA | Claims Processing | CL-001"
    """
    return f"{main_lob} | {state} | {case_type} | {case_id}"


# ============ Change Calculation Utilities ============

def calculate_delta(new_value: float, old_value: float) -> float:
    """
    Calculate delta between new and old values.

    Args:
        new_value: New value
        old_value: Old value

    Returns:
        Delta (new - old)
    """
    return new_value - old_value


def calculate_old_value_from_new_and_delta(new_value: float, delta: float) -> float:
    """
    Calculate old value from new value and delta.

    Args:
        new_value: New value
        delta: Delta (new - old)

    Returns:
        Old value (new - delta)
    """
    return new_value - delta


# ============ Month Abbreviation Utilities ============

def get_month_abbreviation_map() -> Dict[str, str]:
    """
    Get mapping from 3-letter month abbreviation to full month name.

    Returns:
        Dict mapping abbreviation to full name:
        {"Jan": "January", "Feb": "February", ...}
    """
    return {
        "Jan": "January", "Feb": "February", "Mar": "March",
        "Apr": "April", "May": "May", "Jun": "June",
        "Jul": "July", "Aug": "August", "Sep": "September",
        "Oct": "October", "Nov": "November", "Dec": "December"
    }


def parse_month_label(month_label: str) -> tuple:
    """
    Parse month label into month name and year.

    Args:
        month_label: Month label (e.g., "Jun-25")

    Returns:
        Tuple of (full_month_name, full_year)

    Examples:
        parse_month_label("Jun-25") -> ("June", 2025)
        parse_month_label("Dec-24") -> ("December", 2024)
    """
    month_abbr, year_suffix = month_label.split('-')
    month_map = get_month_abbreviation_map()
    full_month = month_map[month_abbr]
    full_year = 2000 + int(year_suffix)
    return (full_month, full_year)
