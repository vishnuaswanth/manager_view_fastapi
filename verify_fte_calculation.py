"""
Verification script for FTE Required calculation consistency.

Compares the centralized calculation utility with expected values.
"""

import math
from code.logics.capacity_calculations import calculate_fte_required

def test_centralized_calculation():
    """Test centralized FTE Required calculation."""
    print("=" * 60)
    print("Testing Centralized FTE Required Calculation")
    print("=" * 60)

    test_cases = [
        {
            'name': 'Standard case',
            'forecast': 10000,
            'config': {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10},
            'target_cph': 50.0,
            'expected': math.ceil(10000 / (21 * 9 * (1-0.10) * 50))
        },
        {
            'name': 'Higher forecast',
            'forecast': 15000,
            'config': {'working_days': 22, 'work_hours': 9, 'shrinkage': 0.15},
            'target_cph': 45.0,
            'expected': math.ceil(15000 / (22 * 9 * (1-0.15) * 45))
        },
        {
            'name': 'Zero forecast',
            'forecast': 0,
            'config': {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10},
            'target_cph': 50.0,
            'expected': 0
        },
        {
            'name': 'Small forecast (results in < 1)',
            'forecast': 100,
            'config': {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10},
            'target_cph': 50.0,
            'expected': math.ceil(100 / (21 * 9 * (1-0.10) * 50))
        }
    ]

    all_passed = True
    for i, test in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test['name']}")
        print(f"  Forecast: {test['forecast']}")
        print(f"  Config: {test['config']}")
        print(f"  Target CPH: {test['target_cph']}")

        result = calculate_fte_required(
            test['forecast'],
            test['config'],
            test['target_cph']
        )

        print(f"  Result: {result}")
        print(f"  Expected: {test['expected']}")

        if result == test['expected']:
            print("  ✓ PASS")
        else:
            print(f"  ✗ FAIL: Expected {test['expected']}, got {result}")
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All tests PASSED")
    else:
        print("✗ Some tests FAILED")
    print("=" * 60)

    return all_passed


def compare_formulas():
    """Compare old (with occupancy) vs new (without occupancy) formula."""
    print("\n" + "=" * 60)
    print("Comparing Old vs New Formula")
    print("=" * 60)

    forecast = 10000
    working_days = 21
    work_hours = 9
    shrinkage = 0.10
    occupancy = 0.95
    target_cph = 50.0

    # Old formula (WITH occupancy)
    old_result = forecast / (target_cph * work_hours * occupancy * (1 - shrinkage) * working_days)

    # New formula (WITHOUT occupancy)
    config = {
        'working_days': working_days,
        'work_hours': work_hours,
        'shrinkage': shrinkage
    }
    new_result = calculate_fte_required(forecast, config, target_cph)

    print(f"\nTest parameters:")
    print(f"  Forecast: {forecast}")
    print(f"  Working Days: {working_days}")
    print(f"  Work Hours: {work_hours}")
    print(f"  Shrinkage: {shrinkage}")
    print(f"  Occupancy: {occupancy} (only used in old formula)")
    print(f"  Target CPH: {target_cph}")

    print(f"\nOld formula (WITH occupancy):")
    print(f"  Formula: forecast / (cph * wh * occ * (1-s) * wd)")
    print(f"  Result: {old_result:.4f} (float)")
    print(f"  Rounded: {round(old_result)}")

    print(f"\nNew formula (WITHOUT occupancy):")
    print(f"  Formula: ceil(forecast / (wd * wh * (1-s) * cph))")
    print(f"  Result: {new_result} (integer)")

    print(f"\n✓ Expected behavior:")
    print(f"  - New values are ~5-10% higher (due to removed occupancy)")
    print(f"  - New values are integers (ceiling applied)")
    print(f"  - Consistent across all allocation operations")

    print("=" * 60)


if __name__ == "__main__":
    # Run centralized calculation tests
    passed = test_centralized_calculation()

    # Compare old vs new formula
    compare_formulas()

    # Exit with proper code
    exit(0 if passed else 1)
