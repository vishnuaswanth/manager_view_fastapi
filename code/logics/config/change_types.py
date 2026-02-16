"""
Change type constants for history logging.

Centralized definitions to ensure consistency between frontend and backend.
As specified in edit_view_api_spec.md Section 4.
"""

# Change Type Constants
CHANGE_TYPE_BENCH_ALLOCATION = "Bench Allocation"
CHANGE_TYPE_CPH_UPDATE = "CPH Update"
CHANGE_TYPE_FORECAST_REALLOCATION = "Forecast Reallocation"
CHANGE_TYPE_MANUAL_UPDATE = "Manual Update"
CHANGE_TYPE_FORECAST_UPDATE = "Forecast Update"

# All valid change types
CHANGE_TYPES = [
    CHANGE_TYPE_BENCH_ALLOCATION,
    CHANGE_TYPE_CPH_UPDATE,
    CHANGE_TYPE_FORECAST_REALLOCATION,
    CHANGE_TYPE_MANUAL_UPDATE,
    CHANGE_TYPE_FORECAST_UPDATE
]


def validate_change_type(change_type: str) -> bool:
    """
    Validate if change type is valid.

    Args:
        change_type: Change type string to validate

    Returns:
        True if valid, False otherwise
    """
    return change_type in CHANGE_TYPES


def get_all_change_types() -> list:
    """
    Get all valid change types.

    Returns:
        List of all valid change type strings
    """
    return CHANGE_TYPES.copy()
