"""
Custom exceptions for Edit View operations.

Provides specific exception types for different failure scenarios with
structured error messages, context, and recommendations.
"""

from typing import Optional, Dict, Any


class EditViewException(Exception):
    """Base exception for Edit View operations."""

    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        recommendation: Optional[str] = None,
        http_status: int = 400
    ):
        self.message = message
        self.context = context or {}
        self.recommendation = recommendation
        self.http_status = http_status
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to structured error response."""
        error_dict = {
            "success": False,
            "error": self.message
        }
        if self.context:
            error_dict["context"] = self.context
        if self.recommendation:
            error_dict["recommendation"] = self.recommendation
        return error_dict


class AllocationValidityException(EditViewException):
    """Raised when allocation is invalid or not found."""

    def __init__(self, month: str, year: int, reason: str, recommendation: str):
        super().__init__(
            message=f"No valid allocation found for {month} {year}: {reason}",
            context={"month": month, "year": year, "reason": reason},
            recommendation=recommendation,
            http_status=400
        )


class ExecutionNotFoundException(EditViewException):
    """Raised when execution record is not found."""

    def __init__(self, execution_id: str):
        super().__init__(
            message=f"Execution record not found: {execution_id}",
            context={"execution_id": execution_id},
            recommendation="Verify that a primary allocation has been run for this month/year.",
            http_status=404
        )


class MonthMappingNotFoundException(EditViewException):
    """Raised when month mappings are not found."""

    def __init__(self, execution_id: str, month: str, year: int):
        super().__init__(
            message=f"Month mappings not found for execution {execution_id}",
            context={
                "execution_id": execution_id,
                "month": month,
                "year": year
            },
            recommendation="The forecast file may not have been uploaded correctly. Re-upload the forecast data.",
            http_status=404
        )


class RosterAllotmentNotFoundException(EditViewException):
    """Raised when roster allotment report is not found."""

    def __init__(self, execution_id: str, month: str, year: int):
        super().__init__(
            message=f"No roster allotment report found for execution {execution_id}",
            context={
                "execution_id": execution_id,
                "month": month,
                "year": year
            },
            recommendation="Run primary allocation first to generate roster allotment data.",
            http_status=404
        )


class EmptyRosterAllotmentException(EditViewException):
    """Raised when roster allotment report exists but is empty."""

    def __init__(self, execution_id: str, month: str, year: int):
        super().__init__(
            message=f"Roster allotment report is empty for execution {execution_id}",
            context={
                "execution_id": execution_id,
                "month": month,
                "year": year
            },
            recommendation="Primary allocation completed but found no vendors. Check roster upload.",
            http_status=404
        )


class ForecastDataNotFoundException(EditViewException):
    """Raised when forecast data is not found."""

    def __init__(self, month: str, year: int, filters: Optional[Dict] = None):
        context = {"month": month, "year": year}
        if filters:
            context["filters"] = filters

        super().__init__(
            message=f"No forecast data found for {month} {year}",
            context=context,
            recommendation="Upload forecast data for this month/year before running allocation.",
            http_status=404
        )


class MonthConfigurationNotFoundException(EditViewException):
    """Raised when month configuration is not found."""

    def __init__(self, month: str, year: int, work_type: str):
        super().__init__(
            message=f"Month configuration not found for {month} {year} ({work_type})",
            context={
                "month": month,
                "year": year,
                "work_type": work_type
            },
            recommendation="Create month configuration before running allocation.",
            http_status=404
        )


class BenchAllocationCompletedException(EditViewException):
    """Raised when bench allocation has already been completed."""

    def __init__(self, month: str, year: int, completed_at: str, execution_id: str):
        super().__init__(
            message=f"Bench allocation already completed for {month} {year}",
            context={
                "month": month,
                "year": year,
                "completed_at": completed_at,
                "execution_id": execution_id
            },
            recommendation="To modify bench allocation, re-run the primary allocation first.",
            http_status=400
        )


class ForecastRecordNotFoundException(EditViewException):
    """Raised when a specific forecast record cannot be found."""

    def __init__(self, main_lob: str, state: str, case_type: str, case_id: str, month: str, year: int):
        super().__init__(
            message=f"Forecast record not found",
            context={
                "main_lob": main_lob,
                "state": state,
                "case_type": case_type,
                "case_id": case_id,
                "month": month,
                "year": year
            },
            recommendation="Verify that the forecast record exists in the database with these exact identifiers.",
            http_status=404
        )
