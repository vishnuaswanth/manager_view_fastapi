"""
Unit tests for custom Edit View exceptions.

Tests that custom exceptions properly structure error information
with context, recommendations, and appropriate HTTP status codes.
"""

import pytest
from code.logics.exceptions import (
    EditViewException,
    AllocationValidityException,
    ExecutionNotFoundException,
    MonthMappingNotFoundException,
    RosterAllotmentNotFoundException,
    EmptyRosterAllotmentException,
    ForecastDataNotFoundException,
    MonthConfigurationNotFoundException,
    BenchAllocationCompletedException,
    ForecastRecordNotFoundException
)


class TestEditViewException:
    """Test base EditViewException functionality."""

    def test_basic_exception_creation(self):
        exc = EditViewException(
            message="Test error",
            context={"key": "value"},
            recommendation="Do something",
            http_status=400
        )

        assert exc.message == "Test error"
        assert exc.context == {"key": "value"}
        assert exc.recommendation == "Do something"
        assert exc.http_status == 400

    def test_to_dict_conversion(self):
        exc = EditViewException(
            message="Test error",
            context={"execution_id": "abc123"},
            recommendation="Check the logs",
            http_status=500
        )

        error_dict = exc.to_dict()

        assert error_dict["success"] == False
        assert error_dict["error"] == "Test error"
        assert error_dict["context"]["execution_id"] == "abc123"
        assert error_dict["recommendation"] == "Check the logs"

    def test_to_dict_without_optional_fields(self):
        exc = EditViewException(message="Simple error")
        error_dict = exc.to_dict()

        assert error_dict["success"] == False
        assert error_dict["error"] == "Simple error"
        assert "context" not in error_dict
        assert "recommendation" not in error_dict


class TestExecutionNotFoundException:
    """Test ExecutionNotFoundException."""

    def test_exception_creation(self):
        exc = ExecutionNotFoundException("abc123")

        assert exc.http_status == 404
        assert "abc123" in exc.message
        assert exc.context["execution_id"] == "abc123"
        assert exc.recommendation is not None
        assert "primary allocation" in exc.recommendation.lower()

    def test_to_dict_structure(self):
        exc = ExecutionNotFoundException("test-exec-id")
        error_dict = exc.to_dict()

        assert error_dict["success"] == False
        assert "error" in error_dict
        assert "recommendation" in error_dict
        assert error_dict["context"]["execution_id"] == "test-exec-id"


class TestMonthMappingNotFoundException:
    """Test MonthMappingNotFoundException."""

    def test_exception_creation(self):
        exc = MonthMappingNotFoundException("exec123", "April", 2025)

        assert exc.http_status == 404
        assert "exec123" in exc.message
        assert exc.context["execution_id"] == "exec123"
        assert exc.context["month"] == "April"
        assert exc.context["year"] == 2025
        assert "forecast" in exc.recommendation.lower()

    def test_to_dict_structure(self):
        exc = MonthMappingNotFoundException("exec123", "May", 2024)
        error_dict = exc.to_dict()

        assert error_dict["success"] == False
        assert error_dict["context"]["month"] == "May"
        assert error_dict["context"]["year"] == 2024


class TestRosterAllotmentNotFoundException:
    """Test RosterAllotmentNotFoundException."""

    def test_exception_creation(self):
        exc = RosterAllotmentNotFoundException("exec123", "April", 2025)

        assert exc.http_status == 404
        assert "roster allotment" in exc.message.lower()
        assert exc.context["execution_id"] == "exec123"
        assert exc.context["month"] == "April"
        assert exc.context["year"] == 2025
        assert "primary allocation" in exc.recommendation.lower()


class TestEmptyRosterAllotmentException:
    """Test EmptyRosterAllotmentException."""

    def test_exception_creation(self):
        exc = EmptyRosterAllotmentException("exec123", "April", 2025)

        assert exc.http_status == 404
        assert "empty" in exc.message.lower()
        assert exc.context["execution_id"] == "exec123"
        assert "vendor" in exc.recommendation.lower()


class TestForecastDataNotFoundException:
    """Test ForecastDataNotFoundException."""

    def test_exception_without_filters(self):
        exc = ForecastDataNotFoundException("April", 2025)

        assert exc.http_status == 404
        assert "forecast data" in exc.message.lower()
        assert exc.context["month"] == "April"
        assert exc.context["year"] == 2025
        assert "filters" not in exc.context
        assert "upload" in exc.recommendation.lower()

    def test_exception_with_filters(self):
        filters = {"status": "after normalization"}
        exc = ForecastDataNotFoundException("April", 2025, filters)

        assert exc.context["filters"] == filters
        assert exc.context["month"] == "April"
        assert exc.context["year"] == 2025


class TestMonthConfigurationNotFoundException:
    """Test MonthConfigurationNotFoundException."""

    def test_exception_creation(self):
        exc = MonthConfigurationNotFoundException("April", 2025, "Domestic")

        assert exc.http_status == 404
        assert "configuration" in exc.message.lower()
        assert exc.context["month"] == "April"
        assert exc.context["year"] == 2025
        assert exc.context["work_type"] == "Domestic"
        assert "create" in exc.recommendation.lower()


class TestBenchAllocationCompletedException:
    """Test BenchAllocationCompletedException."""

    def test_exception_creation(self):
        exc = BenchAllocationCompletedException(
            "April", 2025, "2025-04-15 10:30:00", "exec123"
        )

        assert exc.http_status == 400
        assert "already completed" in exc.message.lower()
        assert exc.context["month"] == "April"
        assert exc.context["year"] == 2025
        assert exc.context["completed_at"] == "2025-04-15 10:30:00"
        assert exc.context["execution_id"] == "exec123"
        assert "re-run" in exc.recommendation.lower()


class TestForecastRecordNotFoundException:
    """Test ForecastRecordNotFoundException."""

    def test_exception_creation(self):
        exc = ForecastRecordNotFoundException(
            "Medicaid IL",
            "CA",
            "Appeals",
            "CASE123",
            "April",
            2025
        )

        assert exc.http_status == 404
        assert "forecast record" in exc.message.lower()
        assert exc.context["main_lob"] == "Medicaid IL"
        assert exc.context["state"] == "CA"
        assert exc.context["case_type"] == "Appeals"
        assert exc.context["case_id"] == "CASE123"
        assert exc.context["month"] == "April"
        assert exc.context["year"] == 2025
        assert "verify" in exc.recommendation.lower()

    def test_to_dict_structure(self):
        exc = ForecastRecordNotFoundException(
            "Medicare TX", "TX", "Grievances", "CASE456", "May", 2024
        )
        error_dict = exc.to_dict()

        assert error_dict["success"] == False
        assert error_dict["context"]["state"] == "TX"
        assert error_dict["context"]["case_type"] == "Grievances"


class TestAllocationValidityException:
    """Test AllocationValidityException."""

    def test_exception_creation(self):
        exc = AllocationValidityException(
            "April",
            2025,
            "No allocation found",
            "Run primary allocation first"
        )

        assert exc.http_status == 400
        assert exc.context["month"] == "April"
        assert exc.context["year"] == 2025
        assert exc.context["reason"] == "No allocation found"
        assert exc.recommendation == "Run primary allocation first"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
