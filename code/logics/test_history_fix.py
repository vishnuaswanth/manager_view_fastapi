"""
Test script to verify history records fix.

Tests that _get_month_data() helper and extract_specific_changes() correctly
handle both flat and nested data structures.
"""

import sys
import os

# Add project root to path for imports
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from code.logics.bench_allocation_transformer import _get_month_data, extract_specific_changes


def test_get_month_data_flat_structure():
    """Test _get_month_data() with flat structure (expected format)."""
    print("\n=== Test 1: Flat Structure ===")

    record = {
        "case_id": "CL-001",
        "main_lob": "Test LOB",
        "Jun-25": {
            "forecast": 1000,
            "fte_req": 20,
            "fte_avail": 25,
            "capacity": 1125,
            "fte_avail_change": 5,
            "capacity_change": 225
        }
    }

    month_data = _get_month_data(record, "Jun-25")

    assert month_data is not None, "Month data should not be None"
    assert month_data["forecast"] == 1000, f"Expected forecast=1000, got {month_data['forecast']}"
    assert month_data["fte_avail"] == 25, f"Expected fte_avail=25, got {month_data['fte_avail']}"
    assert month_data["fte_avail_change"] == 5, f"Expected change=5, got {month_data['fte_avail_change']}"

    print("✓ Flat structure test passed")
    print(f"  Month data: {month_data}")


def test_get_month_data_nested_structure():
    """Test _get_month_data() with nested structure (actual format from preview)."""
    print("\n=== Test 2: Nested Structure ===")

    record = {
        "case_id": "CL-001",
        "main_lob": "Test LOB",
        "months": {
            "Jun-25": {
                "forecast": 1000,
                "fte_req": 20,
                "fte_avail": 25,
                "capacity": 1125,
                "fte_avail_change": 5,
                "capacity_change": 225
            }
        }
    }

    month_data = _get_month_data(record, "Jun-25")

    assert month_data is not None, "Month data should not be None"
    assert month_data["forecast"] == 1000, f"Expected forecast=1000, got {month_data['forecast']}"
    assert month_data["fte_avail"] == 25, f"Expected fte_avail=25, got {month_data['fte_avail']}"
    assert month_data["fte_avail_change"] == 5, f"Expected change=5, got {month_data['fte_avail_change']}"

    print("✓ Nested structure test passed")
    print(f"  Month data: {month_data}")


def test_get_month_data_not_found():
    """Test _get_month_data() when month data not found."""
    print("\n=== Test 3: Month Data Not Found ===")

    record = {
        "case_id": "CL-001",
        "main_lob": "Test LOB"
    }

    month_data = _get_month_data(record, "Jun-25")

    assert month_data is None, "Month data should be None when not found"

    print("✓ Not found test passed")


def test_extract_specific_changes_flat():
    """Test extract_specific_changes() with flat structure."""
    print("\n=== Test 4: Extract Changes - Flat Structure ===")

    modified_records = [{
        "case_id": "CL-001",
        "main_lob": "Amisys Medicaid DOMESTIC",
        "state": "TX",
        "case_type": "Claims Processing",
        "target_cph": 45,
        "target_cph_change": 0,
        "modified_fields": ["Jun-25.fte_avail", "Jun-25.capacity"],
        "Jun-25": {
            "forecast": 1000,
            "fte_req": 20,
            "fte_avail": 25,
            "capacity": 1125,
            "forecast_change": 0,
            "fte_req_change": 0,
            "fte_avail_change": 5,
            "capacity_change": 225
        }
    }]

    months_dict = {"month1": "Jun-25"}

    changes = extract_specific_changes(modified_records, months_dict)

    assert len(changes) == 2, f"Expected 2 changes, got {len(changes)}"

    # Check fte_avail change
    fte_change = next(c for c in changes if c["field_name"] == "Jun-25.fte_avail")
    assert fte_change["old_value"] == 20, f"Expected old_value=20, got {fte_change['old_value']}"
    assert fte_change["new_value"] == 25, f"Expected new_value=25, got {fte_change['new_value']}"
    assert fte_change["delta"] == 5, f"Expected delta=5, got {fte_change['delta']}"

    # Check capacity change
    cap_change = next(c for c in changes if c["field_name"] == "Jun-25.capacity")
    assert cap_change["old_value"] == 900, f"Expected old_value=900, got {cap_change['old_value']}"
    assert cap_change["new_value"] == 1125, f"Expected new_value=1125, got {cap_change['new_value']}"
    assert cap_change["delta"] == 225, f"Expected delta=225, got {cap_change['delta']}"

    print("✓ Extract changes (flat) test passed")
    print(f"  FTE change: old={fte_change['old_value']}, new={fte_change['new_value']}, delta={fte_change['delta']}")
    print(f"  Capacity change: old={cap_change['old_value']}, new={cap_change['new_value']}, delta={cap_change['delta']}")


def test_extract_specific_changes_nested():
    """Test extract_specific_changes() with nested structure."""
    print("\n=== Test 5: Extract Changes - Nested Structure ===")

    modified_records = [{
        "case_id": "CL-001",
        "main_lob": "Amisys Medicaid DOMESTIC",
        "state": "TX",
        "case_type": "Claims Processing",
        "target_cph": 45,
        "target_cph_change": 0,
        "modified_fields": ["Jun-25.fte_avail", "Jun-25.capacity"],
        "months": {
            "Jun-25": {
                "forecast": 1000,
                "fte_req": 20,
                "fte_avail": 25,
                "capacity": 1125,
                "forecast_change": 0,
                "fte_req_change": 0,
                "fte_avail_change": 5,
                "capacity_change": 225
            }
        }
    }]

    months_dict = {"month1": "Jun-25"}

    changes = extract_specific_changes(modified_records, months_dict)

    assert len(changes) == 2, f"Expected 2 changes, got {len(changes)}"

    # Check fte_avail change
    fte_change = next(c for c in changes if c["field_name"] == "Jun-25.fte_avail")
    assert fte_change["old_value"] == 20, f"Expected old_value=20, got {fte_change['old_value']}"
    assert fte_change["new_value"] == 25, f"Expected new_value=25, got {fte_change['new_value']}"
    assert fte_change["delta"] == 5, f"Expected delta=5, got {fte_change['delta']}"

    # Check capacity change
    cap_change = next(c for c in changes if c["field_name"] == "Jun-25.capacity")
    assert cap_change["old_value"] == 900, f"Expected old_value=900, got {cap_change['old_value']}"
    assert cap_change["new_value"] == 1125, f"Expected new_value=1125, got {cap_change['new_value']}"
    assert cap_change["delta"] == 225, f"Expected delta=225, got {cap_change['delta']}"

    print("✓ Extract changes (nested) test passed")
    print(f"  FTE change: old={fte_change['old_value']}, new={fte_change['new_value']}, delta={fte_change['delta']}")
    print(f"  Capacity change: old={cap_change['old_value']}, new={cap_change['new_value']}, delta={cap_change['delta']}")


def test_target_cph_change():
    """Test extract_specific_changes() with target_cph change (month-agnostic field)."""
    print("\n=== Test 6: Target CPH Change (Month-Agnostic) ===")

    modified_records = [{
        "case_id": "CL-001",
        "main_lob": "Amisys Medicaid DOMESTIC",
        "state": "TX",
        "case_type": "Claims Processing",
        "target_cph": 50,
        "target_cph_change": 5,
        "modified_fields": ["target_cph"],
        "months": {
            "Jun-25": {
                "forecast": 1000,
                "fte_req": 18,
                "fte_req_change": -2
            }
        }
    }]

    months_dict = {"month1": "Jun-25"}

    changes = extract_specific_changes(modified_records, months_dict)

    assert len(changes) == 1, f"Expected 1 change, got {len(changes)}"

    cph_change = changes[0]
    assert cph_change["field_name"] == "target_cph", f"Expected field_name='target_cph', got {cph_change['field_name']}"
    assert cph_change["old_value"] == 45, f"Expected old_value=45, got {cph_change['old_value']}"
    assert cph_change["new_value"] == 50, f"Expected new_value=50, got {cph_change['new_value']}"
    assert cph_change["delta"] == 5, f"Expected delta=5, got {cph_change['delta']}"
    assert cph_change["month_label"] is None, "Month label should be None for month-agnostic fields"

    print("✓ Target CPH change test passed")
    print(f"  CPH change: old={cph_change['old_value']}, new={cph_change['new_value']}, delta={cph_change['delta']}")


def run_all_tests():
    """Run all tests."""
    print("=" * 70)
    print("HISTORY RECORDS FIX - TEST SUITE")
    print("=" * 70)

    try:
        test_get_month_data_flat_structure()
        test_get_month_data_nested_structure()
        test_get_month_data_not_found()
        test_extract_specific_changes_flat()
        test_extract_specific_changes_nested()
        test_target_cph_change()

        print("\n" + "=" * 70)
        print("✓ ALL TESTS PASSED")
        print("=" * 70)
        print("\nThe fix correctly handles both flat and nested data structures.")
        print("History records will now show correct old/new values.")

    except AssertionError as e:
        print("\n" + "=" * 70)
        print("✗ TEST FAILED")
        print("=" * 70)
        print(f"\nError: {e}")
        sys.exit(1)
    except Exception as e:
        print("\n" + "=" * 70)
        print("✗ UNEXPECTED ERROR")
        print("=" * 70)
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()
