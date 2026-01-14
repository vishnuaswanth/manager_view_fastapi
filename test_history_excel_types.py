"""
Test script to verify type-safe history Excel generator.

Tests that the new dataclass-based implementation correctly validates input
and prevents value errors.
"""

import sys
import os
from io import BytesIO

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from code.logics.history_excel_generator import (
    HistoryLogData,
    HistoryChangeRecord,
    HistorySummaryData,
    SummaryTotals,
    MonthSummary,
    _get_metric_display_name,
    _prepare_pivot_data,
    _prepare_summary_sheet
)


def test_history_change_record_from_dict():
    """Test HistoryChangeRecord.from_dict() with valid data."""
    print("\n" + "=" * 70)
    print("Test 1: HistoryChangeRecord.from_dict() - Valid Data")
    print("=" * 70)

    data = {
        'main_lob': 'Amisys Medicaid DOMESTIC',
        'state': 'TX',
        'case_type': 'Claims Processing',
        'case_id': 'CL-001',
        'field_name': 'Jun-25.fte_avail',
        'old_value': '20',
        'new_value': '25',
        'delta': 5.0,
        'month_label': 'Jun-25'
    }

    change = HistoryChangeRecord.from_dict(data)

    assert change.main_lob == 'Amisys Medicaid DOMESTIC'
    assert change.state == 'TX'
    assert change.case_type == 'Claims Processing'
    assert change.case_id == 'CL-001'
    assert change.field_name == 'Jun-25.fte_avail'
    assert change.old_value == '20'
    assert change.new_value == '25'
    assert change.delta == 5.0
    assert change.month_label == 'Jun-25'

    print("✓ HistoryChangeRecord created successfully")
    print(f"  Field: {change.field_name}")
    print(f"  Old: {change.old_value}, New: {change.new_value}, Delta: {change.delta}")


def test_history_change_record_missing_keys():
    """Test HistoryChangeRecord.from_dict() with missing required keys."""
    print("\n" + "=" * 70)
    print("Test 2: HistoryChangeRecord.from_dict() - Missing Keys")
    print("=" * 70)

    data = {
        'main_lob': 'Test',
        # Missing: state, case_type, case_id, field_name
    }

    try:
        change = HistoryChangeRecord.from_dict(data)
        print("✗ ERROR: Should have raised KeyError for missing keys")
        assert False
    except KeyError as e:
        print(f"✓ Correctly raised KeyError: {e}")
        assert "Missing required keys" in str(e)


def test_history_log_data_from_dict():
    """Test HistoryLogData.from_dict() with valid data."""
    print("\n" + "=" * 70)
    print("Test 3: HistoryLogData.from_dict() - Valid Data")
    print("=" * 70)

    data = {
        'id': 'abc-123',
        'change_type': 'Bench Allocation',
        'month': 'March',
        'year': 2025,
        'timestamp': '2025-03-15T10:30:00Z',
        'user': 'system',
        'description': 'Test allocation',
        'records_modified': 10,
        'summary_data': {
            'report_month': 'March',
            'report_year': 2025,
            'months': ['Jun-25', 'Jul-25'],
            'totals': {
                'Jun-25': {
                    'total_fte_available': {'old': 100, 'new': 125}
                }
            }
        }
    }

    history_log = HistoryLogData.from_dict(data)

    assert history_log.id == 'abc-123'
    assert history_log.change_type == 'Bench Allocation'
    assert history_log.month == 'March'
    assert history_log.year == 2025
    assert history_log.records_modified == 10
    assert history_log.summary_data is not None
    assert history_log.summary_data.report_month == 'March'

    print("✓ HistoryLogData created successfully")
    print(f"  ID: {history_log.id}")
    print(f"  Type: {history_log.change_type}")
    print(f"  Period: {history_log.month} {history_log.year}")
    print(f"  Records: {history_log.records_modified}")


def test_history_log_data_missing_keys():
    """Test HistoryLogData.from_dict() with missing required keys."""
    print("\n" + "=" * 70)
    print("Test 4: HistoryLogData.from_dict() - Missing Keys")
    print("=" * 70)

    data = {
        'id': 'abc-123',
        'change_type': 'Bench Allocation',
        # Missing: month, year, timestamp, user, records_modified
    }

    try:
        history_log = HistoryLogData.from_dict(data)
        print("✗ ERROR: Should have raised KeyError for missing keys")
        assert False
    except KeyError as e:
        print(f"✓ Correctly raised KeyError: {e}")
        assert "Missing required keys" in str(e)


def test_prepare_pivot_data():
    """Test _prepare_pivot_data() with type-safe HistoryChangeRecord objects."""
    print("\n" + "=" * 70)
    print("Test 5: _prepare_pivot_data() - Type-Safe Objects")
    print("=" * 70)

    changes = [
        HistoryChangeRecord(
            main_lob='Amisys Medicaid DOMESTIC',
            state='TX',
            case_type='Claims Processing',
            case_id='CL-001',
            field_name='Jun-25.fte_avail',
            old_value='20',
            new_value='25',
            delta=5.0,
            month_label='Jun-25'
        ),
        HistoryChangeRecord(
            main_lob='Amisys Medicaid DOMESTIC',
            state='TX',
            case_type='Claims Processing',
            case_id='CL-001',
            field_name='Jun-25.capacity',
            old_value='900',
            new_value='1125',
            delta=225.0,
            month_label='Jun-25'
        )
    ]

    pivot_data = _prepare_pivot_data(changes)

    assert len(pivot_data) == 1  # Should be grouped by case_id
    row = pivot_data[0]

    assert row['Main LOB'] == 'Amisys Medicaid DOMESTIC'
    assert row['State'] == 'TX'
    assert row['Case Type'] == 'Claims Processing'
    assert row['Case ID'] == 'CL-001'
    assert 'Jun-25 FTE Available' in row
    assert row['Jun-25 FTE Available'] == '25 (20)'  # new (old)
    assert 'Jun-25 Capacity' in row
    assert row['Jun-25 Capacity'] == '1125 (900)'

    print("✓ Pivot data prepared successfully")
    print(f"  Rows: {len(pivot_data)}")
    print(f"  FTE Available: {row['Jun-25 FTE Available']}")
    print(f"  Capacity: {row['Jun-25 Capacity']}")


def test_prepare_summary_sheet():
    """Test _prepare_summary_sheet() with type-safe HistoryLogData object."""
    print("\n" + "=" * 70)
    print("Test 6: _prepare_summary_sheet() - Type-Safe Object")
    print("=" * 70)

    # Create summary data
    summary_data = HistorySummaryData(
        report_month='March',
        report_year=2025,
        months=['Jun-25'],
        totals={
            'Jun-25': MonthSummary(
                total_fte_available=SummaryTotals(old=100, new=125)
            )
        }
    )

    history_log = HistoryLogData(
        id='abc-123',
        change_type='Bench Allocation',
        month='March',
        year=2025,
        timestamp='2025-03-15T10:30:00Z',
        user='system',
        description='Test allocation',
        records_modified=10,
        summary_data=summary_data
    )

    summary_rows = _prepare_summary_sheet(history_log)

    assert len(summary_rows) > 0
    assert any(row['label'] == 'History Log ID' and row['value'] == 'abc-123' for row in summary_rows)
    assert any(row['label'] == 'Change Type' and row['value'] == 'Bench Allocation' for row in summary_rows)
    assert any('Total FTE Available (Old)' in row['label'] for row in summary_rows)

    print("✓ Summary sheet prepared successfully")
    print(f"  Rows: {len(summary_rows)}")
    for row in summary_rows[:5]:
        print(f"  {row['label']}: {row['value']}")


def test_get_metric_display_name():
    """Test _get_metric_display_name() function."""
    print("\n" + "=" * 70)
    print("Test 7: _get_metric_display_name()")
    print("=" * 70)

    tests = [
        ('forecast', 'Client Forecast'),
        ('fte_req', 'FTE Required'),
        ('fte_avail', 'FTE Available'),
        ('capacity', 'Capacity'),
        ('target_cph', 'Target CPH'),
        ('custom_field', 'Custom Field')  # Unknown metric
    ]

    for metric, expected in tests:
        result = _get_metric_display_name(metric)
        assert result == expected, f"Expected '{expected}', got '{result}'"
        print(f"  ✓ {metric} → {result}")


def test_backward_compatibility():
    """Test that dict inputs still work (backward compatibility)."""
    print("\n" + "=" * 70)
    print("Test 8: Backward Compatibility with Dict Inputs")
    print("=" * 70)

    # Test with dict input (simulating old API)
    change_dict = {
        'main_lob': 'Test LOB',
        'state': 'TX',
        'case_type': 'Test Type',
        'case_id': 'TEST-001',
        'field_name': 'Jun-25.fte_avail',
        'old_value': '10',
        'new_value': '15',
        'delta': 5.0,
        'month_label': 'Jun-25'
    }

    # Should convert to HistoryChangeRecord internally
    change = HistoryChangeRecord.from_dict(change_dict)
    assert change.main_lob == 'Test LOB'

    # Should be able to convert back to dict
    result_dict = change.to_dict()
    assert result_dict['main_lob'] == 'Test LOB'
    assert result_dict['field_name'] == 'Jun-25.fte_avail'

    print("✓ Backward compatibility maintained")
    print(f"  Dict → Object → Dict: {change.field_name}")


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("HISTORY EXCEL TYPE-SAFETY TEST SUITE")
    print("=" * 70)
    print("\nThis tests the type-safe dataclass implementation for:")
    print("  - HistoryChangeRecord")
    print("  - HistoryLogData")
    print("  - HistorySummaryData")
    print("\nBenefits:")
    print("  - Type validation at creation time")
    print("  - Clear error messages for missing/invalid data")
    print("  - IDE autocomplete and type checking")
    print("  - Prevents value errors at runtime")

    try:
        test_history_change_record_from_dict()
        test_history_change_record_missing_keys()
        test_history_log_data_from_dict()
        test_history_log_data_missing_keys()
        test_prepare_pivot_data()
        test_prepare_summary_sheet()
        test_get_metric_display_name()
        test_backward_compatibility()

        print("\n" + "=" * 70)
        print("✓ ALL TESTS PASSED")
        print("=" * 70)
        print("\nConclusion:")
        print("  - Type-safe dataclasses work correctly")
        print("  - Missing keys are caught with clear error messages")
        print("  - Functions validate input and provide type safety")
        print("  - Backward compatibility maintained with dict inputs")
        print("  - No more generic 'Dict' types - everything is strongly typed!")

    except AssertionError as e:
        print("\n" + "=" * 70)
        print("✗ TEST FAILED")
        print("=" * 70)
        print(f"\nAssertion Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print("\n" + "=" * 70)
        print("✗ UNEXPECTED ERROR")
        print("=" * 70)
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
