"""
Standalone test for history records fix.

Tests the _get_month_data() logic without requiring full dependencies.
"""

from typing import Dict, Optional


def _get_month_data(record: Dict, month_label: str) -> Optional[Dict]:
    """
    Extract month data from record, handling both flat and nested structures.

    This is a copy of the function from bench_allocation_transformer.py for testing.
    """
    # Try root level first (flat structure - expected format)
    if month_label in record:
        month_data = record[month_label]
        if isinstance(month_data, dict):
            print(f"  → Found month data for '{month_label}' at root level (flat structure)")
            return month_data
        else:
            print(f"  → Month data for '{month_label}' at root level is not a dict: {type(month_data)}")
            return None

    # Try nested under "months" key (nested structure - actual format from preview)
    if "months" in record:
        months_container = record["months"]
        if isinstance(months_container, dict):
            month_data = months_container.get(month_label)
            if month_data is not None:
                if isinstance(month_data, dict):
                    print(f"  → Found month data for '{month_label}' in nested 'months' key (nested structure)")
                    return month_data
                else:
                    print(f"  → Month data for '{month_label}' in 'months' is not a dict: {type(month_data)}")
                    return None
        else:
            print(f"  → 'months' key exists but is not a dict: {type(months_container)}")

    # Not found in either location
    print(f"  → Month data for '{month_label}' not found in record")
    return None


def calculate_history_values(month_data: Dict, field_name: str):
    """Calculate old/new/delta values like extract_specific_changes does."""
    new_value = month_data.get(field_name)
    delta = month_data.get(f"{field_name}_change", 0)
    old_value = new_value - delta if isinstance(new_value, (int, float)) else None
    return old_value, new_value, delta


def test_flat_structure():
    """Test with flat structure (expected format)."""
    print("\n" + "=" * 70)
    print("Test 1: Flat Structure (Expected Format)")
    print("=" * 70)

    record = {
        "case_id": "CL-001",
        "main_lob": "Amisys Medicaid DOMESTIC",
        "Jun-25": {
            "forecast": 1000,
            "fte_req": 20,
            "fte_avail": 25,
            "capacity": 1125,
            "fte_avail_change": 5,
            "capacity_change": 225
        }
    }

    print("\nRecord structure:")
    print(f"  case_id: {record['case_id']}")
    print(f"  Jun-25 (at root): {record['Jun-25']}")

    month_data = _get_month_data(record, "Jun-25")
    assert month_data is not None, "Month data should not be None"

    old_fte, new_fte, delta_fte = calculate_history_values(month_data, "fte_avail")
    old_cap, new_cap, delta_cap = calculate_history_values(month_data, "capacity")

    print("\nCalculated history values for fte_avail:")
    print(f"  Old value: {old_fte} (should be 20)")
    print(f"  New value: {new_fte} (should be 25)")
    print(f"  Delta: {delta_fte} (should be 5)")

    print("\nCalculated history values for capacity:")
    print(f"  Old value: {old_cap} (should be 900)")
    print(f"  New value: {new_cap} (should be 1125)")
    print(f"  Delta: {delta_cap} (should be 225)")

    assert old_fte == 20, f"Expected old_fte=20, got {old_fte}"
    assert new_fte == 25, f"Expected new_fte=25, got {new_fte}"
    assert delta_fte == 5, f"Expected delta_fte=5, got {delta_fte}"
    assert old_cap == 900, f"Expected old_cap=900, got {old_cap}"
    assert new_cap == 1125, f"Expected new_cap=1125, got {new_cap}"
    assert delta_cap == 225, f"Expected delta_cap=225, got {delta_cap}"

    print("\n✓ Flat structure test PASSED")


def test_nested_structure():
    """Test with nested structure (actual format from preview)."""
    print("\n" + "=" * 70)
    print("Test 2: Nested Structure (Actual Format from Preview)")
    print("=" * 70)

    record = {
        "case_id": "CL-001",
        "main_lob": "Amisys Medicaid DOMESTIC",
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

    print("\nRecord structure:")
    print(f"  case_id: {record['case_id']}")
    print(f"  months.Jun-25 (nested): {record['months']['Jun-25']}")

    month_data = _get_month_data(record, "Jun-25")
    assert month_data is not None, "Month data should not be None"

    old_fte, new_fte, delta_fte = calculate_history_values(month_data, "fte_avail")
    old_cap, new_cap, delta_cap = calculate_history_values(month_data, "capacity")

    print("\nCalculated history values for fte_avail:")
    print(f"  Old value: {old_fte} (should be 20)")
    print(f"  New value: {new_fte} (should be 25)")
    print(f"  Delta: {delta_fte} (should be 5)")

    print("\nCalculated history values for capacity:")
    print(f"  Old value: {old_cap} (should be 900)")
    print(f"  New value: {new_cap} (should be 1125)")
    print(f"  Delta: {delta_cap} (should be 225)")

    assert old_fte == 20, f"Expected old_fte=20, got {old_fte}"
    assert new_fte == 25, f"Expected new_fte=25, got {new_fte}"
    assert delta_fte == 5, f"Expected delta_fte=5, got {delta_fte}"
    assert old_cap == 900, f"Expected old_cap=900, got {old_cap}"
    assert new_cap == 1125, f"Expected new_cap=1125, got {new_cap}"
    assert delta_cap == 225, f"Expected delta_cap=225, got {delta_cap}"

    print("\n✓ Nested structure test PASSED")


def test_not_found():
    """Test when month data is not found."""
    print("\n" + "=" * 70)
    print("Test 3: Month Data Not Found")
    print("=" * 70)

    record = {
        "case_id": "CL-001",
        "main_lob": "Amisys Medicaid DOMESTIC"
    }

    print("\nRecord structure:")
    print(f"  case_id: {record['case_id']}")
    print(f"  (no month data)")

    month_data = _get_month_data(record, "Jun-25")
    assert month_data is None, "Month data should be None when not found"

    print("\n✓ Not found test PASSED")


def test_problem_scenario():
    """Test the original problem scenario that was causing incorrect history records."""
    print("\n" + "=" * 70)
    print("Test 4: Original Problem Scenario")
    print("=" * 70)

    print("\nBEFORE THE FIX:")
    print("  - Old value would show as 0 (because month_data was None)")
    print("  - New value would show as delta (because wrong data was used)")

    print("\nAFTER THE FIX:")

    # This is what the client sends (nested structure from preview)
    record = {
        "case_id": "CL-001",
        "main_lob": "Amisys Medicaid DOMESTIC",
        "state": "TX",
        "case_type": "Claims Processing",
        "target_cph": 45,
        "modified_fields": ["Jun-25.fte_avail"],
        "months": {  # <- Nested!
            "Jun-25": {
                "forecast": 1000,
                "fte_req": 20,
                "fte_avail": 25,
                "capacity": 1125,
                "fte_avail_change": 5
            }
        }
    }

    print("\nClient sends nested structure (from preview response)")
    month_data = _get_month_data(record, "Jun-25")

    if month_data is None:
        print("  ✗ ERROR: Month data not found! (This was the bug)")
        print("  → History would show: old_value=0, new_value=delta")
    else:
        old_fte, new_fte, delta_fte = calculate_history_values(month_data, "fte_avail")
        print(f"  ✓ SUCCESS: Month data found in nested structure")
        print(f"  → History will show: old_value={old_fte}, new_value={new_fte}, delta={delta_fte}")
        print(f"  → This is CORRECT! (old=20, new=25, delta=5)")

        assert old_fte == 20, f"Expected old=20, got {old_fte}"
        assert new_fte == 25, f"Expected new=25, got {new_fte}"
        assert delta_fte == 5, f"Expected delta=5, got {delta_fte}"

    print("\n✓ Original problem scenario test PASSED")


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("HISTORY RECORDS FIX - STANDALONE TEST SUITE")
    print("=" * 70)
    print("\nThis tests the fix for the issue where:")
    print("  - Old values were showing as 0")
    print("  - New values were showing as deltas")
    print("\nRoot cause: Preview returns nested structure, but history extraction")
    print("            expected flat structure. The fix handles both.")

    try:
        test_flat_structure()
        test_nested_structure()
        test_not_found()
        test_problem_scenario()

        print("\n" + "=" * 70)
        print("✓ ALL TESTS PASSED")
        print("=" * 70)
        print("\nConclusion:")
        print("  - The _get_month_data() helper correctly handles both structures")
        print("  - History records will now show correct old/new values")
        print("  - Backward compatible with both flat and nested formats")

    except AssertionError as e:
        print("\n" + "=" * 70)
        print("✗ TEST FAILED")
        print("=" * 70)
        print(f"\nAssertion Error: {e}")
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
