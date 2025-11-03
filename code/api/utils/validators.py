"""
Request validation utilities for API endpoints.

Provides reusable validation functions for common request parameters
to ensure data integrity and consistency across all endpoints.
"""

from typing import Tuple, Optional
from fastapi import HTTPException
from code.api.utils.responses import error_response


VALID_FILE_IDS = [
    "Forecast",
    "ProdTeamRoster",
    "AllocatedVendorRoster",
    "ForecastMonths"
]

VALID_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]

VALID_STATUSES = ["PENDING", "IN_PROGRESS", "SUCCESS", "FAILED", "PARTIAL_SUCCESS"]


def validate_file_id(file_id: str) -> str:
    """
    Validate file_id parameter.

    Args:
        file_id: The file identifier to validate

    Returns:
        The validated file_id

    Raises:
        HTTPException: If file_id is invalid (400)

    Examples:
        file_id = validate_file_id("Forecast")  # OK
        file_id = validate_file_id("Invalid")   # Raises HTTPException
    """
    if file_id not in VALID_FILE_IDS:
        raise HTTPException(
            status_code=400,
            detail=error_response(
                f"Invalid file_id: {file_id}",
                {"valid_file_ids": VALID_FILE_IDS}
            )
        )
    return file_id


def validate_pagination(
    limit: int,
    offset: int,
    max_limit: int = 100,
    default_limit: int = 50
) -> Tuple[int, int]:
    """
    Validate and normalize pagination parameters.

    Args:
        limit: Maximum records to return
        offset: Pagination offset
        max_limit: Maximum allowed limit (default: 100)
        default_limit: Default limit if not specified (default: 50)

    Returns:
        Tuple of (validated_limit, validated_offset)

    Raises:
        HTTPException: If parameters are invalid (400)

    Examples:
        limit, offset = validate_pagination(50, 0)
        limit, offset = validate_pagination(200, -5)  # Normalizes to (100, 0)
    """
    errors = {}

    # Validate limit
    if limit < 1:
        errors["limit"] = "Must be at least 1"
    elif limit > max_limit:
        limit = max_limit  # Auto-correct to max

    # Validate offset
    if offset < 0:
        errors["offset"] = "Must be non-negative"
        offset = 0  # Auto-correct to 0

    if errors:
        raise HTTPException(
            status_code=400,
            detail=error_response("Invalid pagination parameters", errors)
        )

    return limit, offset


def validate_month(month: str) -> str:
    """
    Validate month parameter.

    Args:
        month: Month name to validate

    Returns:
        The validated month name

    Raises:
        HTTPException: If month is invalid (400)

    Examples:
        month = validate_month("January")  # OK
        month = validate_month("InvalidMonth")  # Raises HTTPException
    """
    if month not in VALID_MONTHS:
        raise HTTPException(
            status_code=400,
            detail=error_response(
                f"Invalid month: {month}",
                {"valid_months": VALID_MONTHS}
            )
        )
    return month


def validate_year(year: int, min_year: int = 2020, max_year: int = 2100) -> int:
    """
    Validate year parameter.

    Args:
        year: Year to validate
        min_year: Minimum allowed year (default: 2020)
        max_year: Maximum allowed year (default: 2100)

    Returns:
        The validated year

    Raises:
        HTTPException: If year is out of range (400)

    Examples:
        year = validate_year(2025)  # OK
        year = validate_year(1900)  # Raises HTTPException
    """
    if year < min_year or year > max_year:
        raise HTTPException(
            status_code=400,
            detail=error_response(
                f"Year {year} out of valid range",
                {"min_year": min_year, "max_year": max_year}
            )
        )
    return year


def validate_execution_status(status: str) -> str:
    """
    Validate allocation execution status.

    Args:
        status: Status string to validate

    Returns:
        The validated status

    Raises:
        HTTPException: If status is invalid (400)

    Examples:
        status = validate_execution_status("SUCCESS")  # OK
        status = validate_execution_status("INVALID")  # Raises HTTPException
    """
    if status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=error_response(
                f"Invalid status: {status}",
                {"valid_statuses": VALID_STATUSES}
            )
        )
    return status


def validate_month_year_pair(month: str, year: int) -> Tuple[str, int]:
    """
    Validate month and year together.

    Args:
        month: Month name
        year: Year number

    Returns:
        Tuple of (validated_month, validated_year)

    Raises:
        HTTPException: If either month or year is invalid (400)

    Examples:
        month, year = validate_month_year_pair("January", 2025)  # OK
    """
    month = validate_month(month)
    year = validate_year(year)
    return month, year
