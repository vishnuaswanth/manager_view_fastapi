"""
Standard response formatters for API endpoints.

Provides consistent response structure across all API endpoints:
- Success responses with optional message
- Error responses with appropriate status codes
- Paginated responses with metadata
"""

from typing import Any, Dict, Optional, List


def success_response(data: Any = None, message: Optional[str] = None) -> Dict:
    """
    Create a standardized success response.

    Args:
        data: The response data (can be dict, list, or any JSON-serializable type)
        message: Optional success message

    Returns:
        {
            "success": true,
            "message": "...",  # Optional
            "data": {...}       # Optional
        }

    Examples:
        success_response({"id": 123}, "Created successfully")
        success_response([{...}, {...}])
        success_response(message="Operation completed")
    """
    response = {"success": True}

    if message:
        response["message"] = message

    if data is not None:
        response["data"] = data

    return response


def error_response(message: str, details: Optional[Any] = None) -> Dict:
    """
    Create a standardized error response.

    Note: This returns the response body only. The HTTPException status_code
    should be set separately when raising the exception.

    Args:
        message: Error message
        details: Optional additional error details

    Returns:
        {
            "success": false,
            "error": "...",
            "details": {...}  # Optional
        }

    Examples:
        raise HTTPException(status_code=400, detail=error_response("Invalid input"))
        raise HTTPException(status_code=404, detail=error_response("Not found", {"id": 123}))
    """
    response = {
        "success": False,
        "error": message
    }

    if details is not None:
        response["details"] = details

    return response


def paginated_response(
    data: List[Any],
    total: int,
    limit: int,
    offset: int,
    message: Optional[str] = None
) -> Dict:
    """
    Create a standardized paginated response.

    Args:
        data: List of records for current page
        total: Total number of records available
        limit: Maximum records per page
        offset: Current pagination offset
        message: Optional message

    Returns:
        {
            "success": true,
            "message": "...",      # Optional
            "data": [...],
            "pagination": {
                "total": 150,
                "limit": 50,
                "offset": 0,
                "count": 50,       # Records in current page
                "has_more": true   # Whether more pages exist
            }
        }

    Examples:
        paginated_response(records, total=150, limit=50, offset=0)
    """
    response = {
        "success": True,
        "data": data,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "count": len(data),
            "has_more": (offset + len(data)) < total
        }
    }

    if message:
        response["message"] = message

    return response


def validation_error_response(errors: Dict[str, str]) -> Dict:
    """
    Create a standardized validation error response.

    Args:
        errors: Dictionary mapping field names to error messages

    Returns:
        {
            "success": false,
            "error": "Validation failed",
            "validation_errors": {
                "field_name": "error message",
                ...
            }
        }

    Examples:
        validation_error_response({"email": "Invalid email format", "age": "Must be positive"})
    """
    return {
        "success": False,
        "error": "Validation failed",
        "validation_errors": errors
    }
