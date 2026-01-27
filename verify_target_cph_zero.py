"""
Verification script for target_cph = 0 handling in capacity calculations.

Tests that FTE Required and Capacity calculations correctly handle target_cph = 0.
"""

import sys
import os

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from code.logics.capacity_calculations import calculate_fte_required, calculate_capacity


def test_fte_required_with_zero_cph():
    """Test FTE Required calculation with target_cph = 0."""
    print("\n" + "=" * 70)
    print("Testing FTE Required with target_cph = 0")
    print("=" * 70)

    config = {
        'working_days': 21,
        'work_hours': 9,
        'shrinkage': 0.10
    }

    # Test 1: Normal forecast with target_cph = 0
    forecast = 10000
    target_cph = 0
    result = calculate_fte_required(forecast, config, target_cph)

    print(f"\nTest 1: Forecast={forecast}, target_cph={target_cph}")
    print(f"  Result: {result}")
    print(f"  Expected: 0")
    assert result == 0, f"Expected 0, got {result}"
    print("  ✓ PASS")

    # Test 2: Zero forecast with target_cph = 0
    forecast = 0
    target_cph = 0
    result = calculate_fte_required(forecast, config, target_cph)

    print(f"\nTest 2: Forecast={forecast}, target_cph={target_cph}")
    print(f"  Result: {result}")
    print(f"  Expected: 0")
    assert result == 0, f"Expected 0, got {result}"
    print("  ✓ PASS")

    # Test 3: Large forecast with target_cph = 0
    forecast = 100000
    target_cph = 0
    result = calculate_fte_required(forecast, config, target_cph)

    print(f"\nTest 3: Forecast={forecast}, target_cph={target_cph}")
    print(f"  Result: {result}")
    print(f"  Expected: 0")
    assert result == 0, f"Expected 0, got {result}"
    print("  ✓ PASS")

    return True


def test_capacity_with_zero_cph():
    """Test Capacity calculation with target_cph = 0."""
    print("\n" + "=" * 70)
    print("Testing Capacity with target_cph = 0")
    print("=" * 70)

    config = {
        'working_days': 21,
        'work_hours': 9,
        'shrinkage': 0.10
    }

    # Test 1: Normal FTE with target_cph = 0
    fte_avail = 10
    target_cph = 0
    result = calculate_capacity(fte_avail, config, target_cph)

    print(f"\nTest 1: FTE={fte_avail}, target_cph={target_cph}")
    print(f"  Result: {result}")
    print(f"  Expected: 0.0")
    assert result == 0.0, f"Expected 0.0, got {result}"
    print("  ✓ PASS")

    # Test 2: Zero FTE with target_cph = 0
    fte_avail = 0
    target_cph = 0
    result = calculate_capacity(fte_avail, config, target_cph)

    print(f"\nTest 2: FTE={fte_avail}, target_cph={target_cph}")
    print(f"  Result: {result}")
    print(f"  Expected: 0.0")
    assert result == 0.0, f"Expected 0.0, got {result}"
    print("  ✓ PASS")

    # Test 3: Large FTE with target_cph = 0
    fte_avail = 100
    target_cph = 0
    result = calculate_capacity(fte_avail, config, target_cph)

    print(f"\nTest 3: FTE={fte_avail}, target_cph={target_cph}")
    print(f"  Result: {result}")
    print(f"  Expected: 0.0")
    assert result == 0.0, f"Expected 0.0, got {result}"
    print("  ✓ PASS")

    return True


def test_normal_calculations_still_work():
    """Verify normal calculations with positive target_cph still work."""
    print("\n" + "=" * 70)
    print("Testing Normal Calculations (target_cph > 0)")
    print("=" * 70)

    config = {
        'working_days': 21,
        'work_hours': 9,
        'shrinkage': 0.10
    }

    # Test FTE Required
    forecast = 10000
    target_cph = 50.0
    fte_result = calculate_fte_required(forecast, config, target_cph)

    print(f"\nFTE Required Test: Forecast={forecast}, target_cph={target_cph}")
    print(f"  Result: {fte_result}")
    print(f"  Expected: 2")
    assert fte_result == 2, f"Expected 2, got {fte_result}"
    print("  ✓ PASS")

    # Test Capacity
    fte_avail = 10
    target_cph = 50.0
    capacity_result = calculate_capacity(fte_avail, config, target_cph)

    print(f"\nCapacity Test: FTE={fte_avail}, target_cph={target_cph}")
    print(f"  Result: {capacity_result}")
    print(f"  Expected: 85050.0")
    # Calculation: 10 * 21 * 9 * 0.90 * 50 = 85050.0
    assert capacity_result == 85050.0, f"Expected 85050.0, got {capacity_result}"
    print("  ✓ PASS")

    return True


def test_negative_cph_rejected():
    """Verify negative target_cph is rejected."""
    print("\n" + "=" * 70)
    print("Testing Negative target_cph Rejection")
    print("=" * 70)

    config = {
        'working_days': 21,
        'work_hours': 9,
        'shrinkage': 0.10
    }

    # Test FTE Required with negative CPH
    try:
        result = calculate_fte_required(1000, config, -10)
        print("\n✗ FAIL: Should have raised ValueError for negative target_cph")
        return False
    except ValueError as e:
        print(f"\n✓ PASS: Correctly rejected negative target_cph")
        print(f"  Error: {e}")

    # Test Capacity with negative CPH
    try:
        result = calculate_capacity(10, config, -10)
        print("\n✗ FAIL: Should have raised ValueError for negative target_cph")
        return False
    except ValueError as e:
        print(f"\n✓ PASS: Correctly rejected negative target_cph")
        print(f"  Error: {e}")

    return True


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("TARGET CPH = 0 VERIFICATION")
    print("=" * 70)

    tests = [
        ("FTE Required with target_cph = 0", test_fte_required_with_zero_cph),
        ("Capacity with target_cph = 0", test_capacity_with_zero_cph),
        ("Normal calculations still work", test_normal_calculations_still_work),
        ("Negative target_cph rejection", test_negative_cph_rejected)
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
                print(f"\n✗ {test_name} FAILED")
        except AssertionError as e:
            print(f"\n✗ {test_name} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"\n✗ {test_name} ERROR: {e}")
            failed += 1

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Tests passed: {passed}")
    print(f"  Tests failed: {failed}")
    print("=" * 70)

    if failed == 0:
        print("\n✓ ALL TESTS PASSED")
        print("\nConclusion:")
        print("  - target_cph = 0 is now allowed")
        print("  - FTE Required returns 0 when target_cph = 0")
        print("  - Capacity returns 0.0 when target_cph = 0")
        print("  - Normal calculations (target_cph > 0) still work")
        print("  - Negative target_cph is correctly rejected")
        return 0
    else:
        print("\n✗ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    exit(main())
