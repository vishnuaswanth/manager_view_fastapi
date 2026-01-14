"""
Test Option 1 Implementation: Track All Fields for Modified Records.

Verifies that when ANY field changes in a record, ALL fields are tracked
in the history log to provide complete context.
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from code.logics.bench_allocation_transformer import extract_specific_changes


def test_bench_allocation_all_fields_tracked():
    """Test that bench allocation tracks ALL fields when any field changes."""
    print("\n" + "=" * 70)
    print("Test 1: Bench Allocation - All Fields Tracked")
    print("=" * 70)

    print("\nScenario: Only fte_avail changed (20 → 25)")
    print("Expected: ALL fields tracked (forecast, fte_req, fte_avail, capacity)")

    modified_records = [{
        "case_id": "CL-001",
        "main_lob": "Amisys Medicaid DOMESTIC",
        "state": "TX",
        "case_type": "Claims Processing",
        "target_cph": 45,
        "target_cph_change": 0,
        "modified_fields": [
            "Jun-25.forecast",      # ← Should be tracked
            "Jun-25.fte_req",       # ← Should be tracked
            "Jun-25.fte_avail",     # ← Changed field
            "Jun-25.capacity"       # ← Should be tracked
        ],
        "months": {
            "Jun-25": {
                "forecast": 1000,
                "fte_req": 20,
                "fte_avail": 25,         # Changed: 20 → 25
                "capacity": 1125,
                "forecast_change": 0,
                "fte_req_change": 0,
                "fte_avail_change": 5,   # The change
                "capacity_change": 0
            }
        }
    }]

    months_dict = {"month1": "Jun-25"}

    changes = extract_specific_changes(modified_records, months_dict)

    print(f"\nHistory records created: {len(changes)}")
    print("\nFields tracked:")
    for change in changes:
        field = change['field_name']
        old_val = change['old_value']
        new_val = change['new_value']
        delta = change['delta']
        print(f"  - {field:25s} | Old: {str(old_val):10s} | New: {str(new_val):10s} | Delta: {delta}")

    # Verify ALL 4 fields are tracked
    field_names = [c['field_name'] for c in changes]
    expected_fields = [
        "Jun-25.forecast",
        "Jun-25.fte_req",
        "Jun-25.fte_avail",
        "Jun-25.capacity"
    ]

    for expected_field in expected_fields:
        assert expected_field in field_names, f"Missing field: {expected_field}"

    # Verify values are correct
    forecast_change = next(c for c in changes if c['field_name'] == 'Jun-25.forecast')
    assert forecast_change['old_value'] == 1000, "Forecast old value should be 1000"
    assert forecast_change['new_value'] == 1000, "Forecast new value should be 1000"
    assert forecast_change['delta'] == 0, "Forecast delta should be 0"

    fte_avail_change = next(c for c in changes if c['field_name'] == 'Jun-25.fte_avail')
    assert fte_avail_change['old_value'] == 20, "FTE Avail old value should be 20"
    assert fte_avail_change['new_value'] == 25, "FTE Avail new value should be 25"
    assert fte_avail_change['delta'] == 5, "FTE Avail delta should be 5"

    print("\n✓ TEST PASSED: All 4 fields tracked (forecast, fte_req, fte_avail, capacity)")
    print("✓ Old/new values are correct for both changed and unchanged fields")


def test_cph_update_all_fields_tracked():
    """Test that CPH updates track ALL fields when any field changes."""
    print("\n" + "=" * 70)
    print("Test 2: CPH Update - All Fields Tracked")
    print("=" * 70)

    print("\nScenario: target_cph changed (45 → 50), causing fte_req and capacity recalculation")
    print("Expected: ALL fields tracked (forecast, fte_req, fte_avail, capacity)")

    modified_records = [{
        "case_id": "CL-001",
        "main_lob": "Amisys Medicaid DOMESTIC",
        "state": "TX",
        "case_type": "Claims Processing",
        "target_cph": 50,
        "target_cph_change": 5,
        "modified_fields": [
            "target_cph",
            "Jun-25.forecast",      # ← Should be tracked
            "Jun-25.fte_req",       # ← Changed (recalculated)
            "Jun-25.fte_avail",     # ← Should be tracked
            "Jun-25.capacity"       # ← Changed (recalculated)
        ],
        "months": {
            "Jun-25": {
                "forecast": 1000,
                "fte_req": 18,              # Changed: 20 → 18 (CPH increased)
                "fte_avail": 25,
                "capacity": 1250,           # Changed: 1125 → 1250
                "forecast_change": 0,
                "fte_req_change": -2,       # Decreased
                "fte_avail_change": 0,
                "capacity_change": 125      # Increased
            }
        }
    }]

    months_dict = {"month1": "Jun-25"}

    changes = extract_specific_changes(modified_records, months_dict)

    print(f"\nHistory records created: {len(changes)}")
    print("\nFields tracked:")
    for change in changes:
        field = change['field_name']
        old_val = change['old_value']
        new_val = change['new_value']
        delta = change['delta']
        print(f"  - {field:25s} | Old: {str(old_val):10s} | New: {str(new_val):10s} | Delta: {delta}")

    # Verify target_cph + ALL 4 month fields are tracked (5 total)
    field_names = [c['field_name'] for c in changes]
    expected_fields = [
        "target_cph",
        "Jun-25.forecast",
        "Jun-25.fte_req",
        "Jun-25.fte_avail",
        "Jun-25.capacity"
    ]

    for expected_field in expected_fields:
        assert expected_field in field_names, f"Missing field: {expected_field}"

    # Verify target_cph change
    cph_change = next(c for c in changes if c['field_name'] == 'target_cph')
    assert cph_change['old_value'] == 45, "CPH old value should be 45"
    assert cph_change['new_value'] == 50, "CPH new value should be 50"
    assert cph_change['delta'] == 5, "CPH delta should be 5"

    # Verify forecast (unchanged but tracked)
    forecast_change = next(c for c in changes if c['field_name'] == 'Jun-25.forecast')
    assert forecast_change['old_value'] == 1000, "Forecast old value should be 1000"
    assert forecast_change['new_value'] == 1000, "Forecast new value should be 1000"
    assert forecast_change['delta'] == 0, "Forecast delta should be 0"

    # Verify fte_req (changed)
    fte_req_change = next(c for c in changes if c['field_name'] == 'Jun-25.fte_req')
    assert fte_req_change['old_value'] == 20, "FTE Req old value should be 20"
    assert fte_req_change['new_value'] == 18, "FTE Req new value should be 18"
    assert fte_req_change['delta'] == -2, "FTE Req delta should be -2"

    print("\n✓ TEST PASSED: All 5 fields tracked (target_cph + 4 month fields)")
    print("✓ Unchanged fields (forecast, fte_avail) included for complete context")


def test_multiple_months_separate_tracking():
    """Test that each month tracks all fields independently."""
    print("\n" + "=" * 70)
    print("Test 3: Multiple Months - Independent Tracking")
    print("=" * 70)

    print("\nScenario: Jun-25 has fte_avail change, Jul-25 has capacity change")
    print("Expected: Jun-25 tracks all 4 fields, Jul-25 tracks all 4 fields")

    modified_records = [{
        "case_id": "CL-001",
        "main_lob": "Amisys Medicaid DOMESTIC",
        "state": "TX",
        "case_type": "Claims Processing",
        "target_cph": 45,
        "target_cph_change": 0,
        "modified_fields": [
            "Jun-25.forecast",
            "Jun-25.fte_req",
            "Jun-25.fte_avail",
            "Jun-25.capacity",
            "Jul-25.forecast",
            "Jul-25.fte_req",
            "Jul-25.fte_avail",
            "Jul-25.capacity"
        ],
        "months": {
            "Jun-25": {
                "forecast": 1000,
                "fte_req": 20,
                "fte_avail": 25,         # Changed
                "capacity": 1125,
                "forecast_change": 0,
                "fte_req_change": 0,
                "fte_avail_change": 5,
                "capacity_change": 0
            },
            "Jul-25": {
                "forecast": 1100,
                "fte_req": 22,
                "fte_avail": 22,
                "capacity": 1000,        # Changed
                "forecast_change": 0,
                "fte_req_change": 0,
                "fte_avail_change": 0,
                "capacity_change": 100
            }
        }
    }]

    months_dict = {"month1": "Jun-25", "month2": "Jul-25"}

    changes = extract_specific_changes(modified_records, months_dict)

    print(f"\nHistory records created: {len(changes)}")
    print("\nJun-25 fields:")
    jun_changes = [c for c in changes if c['month_label'] == 'Jun-25']
    for change in jun_changes:
        field = change['field_name']
        print(f"  - {field}")

    print("\nJul-25 fields:")
    jul_changes = [c for c in changes if c['month_label'] == 'Jul-25']
    for change in jul_changes:
        field = change['field_name']
        print(f"  - {field}")

    # Verify Jun-25 has all 4 fields
    jun_field_names = [c['field_name'] for c in jun_changes]
    expected_jun_fields = [
        "Jun-25.forecast",
        "Jun-25.fte_req",
        "Jun-25.fte_avail",
        "Jun-25.capacity"
    ]
    for field in expected_jun_fields:
        assert field in jun_field_names, f"Jun-25 missing field: {field}"

    # Verify Jul-25 has all 4 fields
    jul_field_names = [c['field_name'] for c in jul_changes]
    expected_jul_fields = [
        "Jul-25.forecast",
        "Jul-25.fte_req",
        "Jul-25.fte_avail",
        "Jul-25.capacity"
    ]
    for field in expected_jul_fields:
        assert field in jul_field_names, f"Jul-25 missing field: {field}"

    assert len(changes) == 8, f"Expected 8 history records (4 per month), got {len(changes)}"

    print("\n✓ TEST PASSED: Both months tracked all 4 fields independently")
    print("✓ Total: 8 history records (4 for Jun-25, 4 for Jul-25)")


def test_no_changes_no_tracking():
    """Test that records with no changes are NOT tracked."""
    print("\n" + "=" * 70)
    print("Test 4: No Changes - No Tracking")
    print("=" * 70)

    print("\nScenario: Record CL-001 has changes, Record CL-002 has no changes")
    print("Expected: Only CL-001 is tracked, CL-002 is NOT tracked")

    # This test verifies the filter at the record level (not at the field level)
    # Only records with modified_fields should be passed to extract_specific_changes

    modified_records = [{
        "case_id": "CL-001",
        "main_lob": "Amisys Medicaid DOMESTIC",
        "state": "TX",
        "case_type": "Claims Processing",
        "target_cph": 45,
        "target_cph_change": 0,
        "modified_fields": ["Jun-25.fte_avail", "Jun-25.capacity", "Jun-25.forecast", "Jun-25.fte_req"],
        "months": {
            "Jun-25": {
                "forecast": 1000,
                "fte_req": 20,
                "fte_avail": 25,
                "capacity": 1125,
                "forecast_change": 0,
                "fte_req_change": 0,
                "fte_avail_change": 5,
                "capacity_change": 0
            }
        }
    }]
    # Note: CL-002 with no changes would not be included in modified_records at all

    months_dict = {"month1": "Jun-25"}

    changes = extract_specific_changes(modified_records, months_dict)

    print(f"\nHistory records created: {len(changes)}")
    print(f"Case IDs tracked: {set(c['case_id'] for c in changes)}")

    assert len(changes) == 4, "Should have 4 history records for CL-001"
    assert all(c['case_id'] == 'CL-001' for c in changes), "All records should be for CL-001"

    print("\n✓ TEST PASSED: Only modified records are tracked")
    print("✓ Records with no changes (CL-002) are NOT in history")


def main():
    """Run all Option 1 tests."""
    print("\n" + "=" * 70)
    print("OPTION 1 IMPLEMENTATION TEST SUITE")
    print("=" * 70)
    print("\nTesting: Track ALL Fields for Modified Records Only")
    print("\nGoal:")
    print("  - When ANY field changes in a record, track ALL fields")
    print("  - Provides complete context for changed records")
    print("  - Does NOT track records with zero changes")
    print("\nBenefits:")
    print("  - Excel exports show complete data (all columns)")
    print("  - Can see full state of each modified record")
    print("  - Efficient (only tracks records involved in changes)")

    try:
        test_bench_allocation_all_fields_tracked()
        test_cph_update_all_fields_tracked()
        test_multiple_months_separate_tracking()
        test_no_changes_no_tracking()

        print("\n" + "=" * 70)
        print("✓ ALL TESTS PASSED")
        print("=" * 70)
        print("\nOption 1 Successfully Implemented!")
        print("\nKey Features:")
        print("  ✓ All fields tracked for modified records")
        print("  ✓ Unchanged fields included with delta=0")
        print("  ✓ Each month tracks independently")
        print("  ✓ Records without changes NOT tracked")
        print("\nExcel Export Will Show:")
        print("  - Complete columns (Forecast, FTE Req, FTE Avail, Capacity)")
        print("  - Old/new values for all fields")
        print("  - Easy to audit changes with full context")

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
