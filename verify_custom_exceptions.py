"""
Simple verification script for custom exceptions (without pytest).

Verifies that custom exceptions properly structure error information
with context, recommendations, and appropriate HTTP status codes.
"""

from code.logics.exceptions import (
    EditViewException,
    ExecutionNotFoundException,
    MonthMappingNotFoundException,
    RosterAllotmentNotFoundException,
    EmptyRosterAllotmentException,
    ForecastDataNotFoundException,
    MonthConfigurationNotFoundException,
    BenchAllocationCompletedException,
    ForecastRecordNotFoundException
)


def test_base_exception():
    """Test base EditViewException."""
    print("\n" + "=" * 70)
    print("Testing EditViewException")
    print("=" * 70)

    exc = EditViewException(
        message="Test error",
        context={"execution_id": "abc123"},
        recommendation="Check the logs",
        http_status=500
    )

    error_dict = exc.to_dict()

    assert error_dict["success"] == False, "success should be False"
    assert error_dict["error"] == "Test error", "error message mismatch"
    assert error_dict["context"]["execution_id"] == "abc123", "context missing"
    assert error_dict["recommendation"] == "Check the logs", "recommendation missing"

    print("✓ Base exception creation: PASS")
    print(f"  Error dict: {error_dict}")


def test_execution_not_found():
    """Test ExecutionNotFoundException."""
    print("\n" + "=" * 70)
    print("Testing ExecutionNotFoundException")
    print("=" * 70)

    exc = ExecutionNotFoundException("abc123")

    assert exc.http_status == 404, "HTTP status should be 404"
    assert "abc123" in exc.message, "execution_id should be in message"
    assert exc.context["execution_id"] == "abc123", "context should have execution_id"
    assert exc.recommendation is not None, "recommendation should not be None"

    error_dict = exc.to_dict()
    print("✓ ExecutionNotFoundException: PASS")
    print(f"  Message: {exc.message}")
    print(f"  Context: {exc.context}")
    print(f"  Recommendation: {exc.recommendation}")
    print(f"  HTTP Status: {exc.http_status}")


def test_month_mapping_not_found():
    """Test MonthMappingNotFoundException."""
    print("\n" + "=" * 70)
    print("Testing MonthMappingNotFoundException")
    print("=" * 70)

    exc = MonthMappingNotFoundException("exec123", "April", 2025)

    assert exc.http_status == 404, "HTTP status should be 404"
    assert exc.context["execution_id"] == "exec123"
    assert exc.context["month"] == "April"
    assert exc.context["year"] == 2025

    print("✓ MonthMappingNotFoundException: PASS")
    print(f"  Message: {exc.message}")
    print(f"  Context: {exc.context}")


def test_roster_allotment_not_found():
    """Test RosterAllotmentNotFoundException."""
    print("\n" + "=" * 70)
    print("Testing RosterAllotmentNotFoundException")
    print("=" * 70)

    exc = RosterAllotmentNotFoundException("exec123", "April", 2025)

    assert exc.http_status == 404
    assert "roster allotment" in exc.message.lower()
    assert "primary allocation" in exc.recommendation.lower()

    print("✓ RosterAllotmentNotFoundException: PASS")
    print(f"  Message: {exc.message}")
    print(f"  Recommendation: {exc.recommendation}")


def test_empty_roster_allotment():
    """Test EmptyRosterAllotmentException."""
    print("\n" + "=" * 70)
    print("Testing EmptyRosterAllotmentException")
    print("=" * 70)

    exc = EmptyRosterAllotmentException("exec123", "April", 2025)

    assert exc.http_status == 404
    assert "empty" in exc.message.lower()

    print("✓ EmptyRosterAllotmentException: PASS")
    print(f"  Message: {exc.message}")


def test_forecast_data_not_found():
    """Test ForecastDataNotFoundException."""
    print("\n" + "=" * 70)
    print("Testing ForecastDataNotFoundException")
    print("=" * 70)

    # Without filters
    exc1 = ForecastDataNotFoundException("April", 2025)
    assert exc1.http_status == 404
    assert "filters" not in exc1.context

    # With filters
    exc2 = ForecastDataNotFoundException("April", 2025, {"status": "after normalization"})
    assert exc2.context["filters"] == {"status": "after normalization"}

    print("✓ ForecastDataNotFoundException: PASS")
    print(f"  Message (without filters): {exc1.message}")
    print(f"  Message (with filters): {exc2.message}")
    print(f"  Context (with filters): {exc2.context}")


def test_month_configuration_not_found():
    """Test MonthConfigurationNotFoundException."""
    print("\n" + "=" * 70)
    print("Testing MonthConfigurationNotFoundException")
    print("=" * 70)

    exc = MonthConfigurationNotFoundException("April", 2025, "Domestic")

    assert exc.http_status == 404
    assert exc.context["work_type"] == "Domestic"

    print("✓ MonthConfigurationNotFoundException: PASS")
    print(f"  Message: {exc.message}")


def test_bench_allocation_completed():
    """Test BenchAllocationCompletedException."""
    print("\n" + "=" * 70)
    print("Testing BenchAllocationCompletedException")
    print("=" * 70)

    exc = BenchAllocationCompletedException(
        "April", 2025, "2025-04-15 10:30:00", "exec123"
    )

    assert exc.http_status == 400
    assert "already completed" in exc.message.lower()
    assert exc.context["completed_at"] == "2025-04-15 10:30:00"

    print("✓ BenchAllocationCompletedException: PASS")
    print(f"  Message: {exc.message}")
    print(f"  Context: {exc.context}")


def test_forecast_record_not_found():
    """Test ForecastRecordNotFoundException."""
    print("\n" + "=" * 70)
    print("Testing ForecastRecordNotFoundException")
    print("=" * 70)

    exc = ForecastRecordNotFoundException(
        "Medicaid IL",
        "CA",
        "Appeals",
        "CASE123",
        "April",
        2025
    )

    assert exc.http_status == 404
    assert exc.context["main_lob"] == "Medicaid IL"
    assert exc.context["state"] == "CA"
    assert exc.context["case_type"] == "Appeals"

    error_dict = exc.to_dict()

    print("✓ ForecastRecordNotFoundException: PASS")
    print(f"  Message: {exc.message}")
    print(f"  Context: {exc.context}")
    print(f"  Error dict: {error_dict}")


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("CUSTOM EXCEPTIONS VERIFICATION")
    print("=" * 70)

    tests = [
        test_base_exception,
        test_execution_not_found,
        test_month_mapping_not_found,
        test_roster_allotment_not_found,
        test_empty_roster_allotment,
        test_forecast_data_not_found,
        test_month_configuration_not_found,
        test_bench_allocation_completed,
        test_forecast_record_not_found
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"\n✗ {test_func.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"\n✗ {test_func.__name__} ERROR: {e}")
            failed += 1

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Tests passed: {passed}")
    print(f"  Tests failed: {failed}")
    print("=" * 70)

    if failed == 0:
        print("✓ ALL TESTS PASSED")
        print("\nConclusion:")
        print("  - All custom exceptions work correctly")
        print("  - Error messages are properly structured")
        print("  - Context and recommendations are included")
        print("  - HTTP status codes are appropriate")
        return 0
    else:
        print("✗ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    exit(main())
