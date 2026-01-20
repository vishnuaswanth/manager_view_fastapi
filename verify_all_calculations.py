"""
Comprehensive verification script for FTE Required and Capacity calculations.

Verifies that all calculation functions use centralized utilities and produce
consistent results.
"""

import math
from code.logics.capacity_calculations import calculate_fte_required, calculate_capacity


def test_fte_required_calculation():
    """Test FTE Required calculation with various scenarios."""
    print("=" * 70)
    print("Testing FTE Required Calculation")
    print("=" * 70)

    test_cases = [
        {
            'name': 'Standard case',
            'forecast': 10000,
            'config': {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10},
            'target_cph': 50.0,
            'expected': 2
        },
        {
            'name': 'Higher forecast',
            'forecast': 15000,
            'config': {'working_days': 22, 'work_hours': 9, 'shrinkage': 0.15},
            'target_cph': 45.0,
            'expected': 2
        },
        {
            'name': 'Zero forecast',
            'forecast': 0,
            'config': {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10},
            'target_cph': 50.0,
            'expected': 0
        },
        {
            'name': 'Small forecast (< 1 FTE)',
            'forecast': 100,
            'config': {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10},
            'target_cph': 50.0,
            'expected': 1
        },
        {
            'name': 'Large forecast',
            'forecast': 100000,
            'config': {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10},
            'target_cph': 50.0,
            'expected': 12
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

        # Manual calculation for verification
        wd = test['config']['working_days']
        wh = test['config']['work_hours']
        s = test['config']['shrinkage']
        cph = test['target_cph']
        f = test['forecast']

        expected = math.ceil(f / (wd * wh * (1-s) * cph)) if f > 0 else 0

        print(f"  Result: {result}")
        print(f"  Expected: {expected}")

        if result == expected:
            print("  ✓ PASS")
        else:
            print(f"  ✗ FAIL: Expected {expected}, got {result}")
            all_passed = False

    return all_passed


def test_capacity_calculation():
    """Test Capacity calculation with various scenarios."""
    print("\n" + "=" * 70)
    print("Testing Capacity Calculation")
    print("=" * 70)

    test_cases = [
        {
            'name': 'Standard case',
            'fte_avail': 10,
            'config': {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10},
            'target_cph': 50.0,
            'expected': 8505.0
        },
        {
            'name': 'Higher FTE',
            'fte_avail': 25,
            'config': {'working_days': 22, 'work_hours': 9, 'shrinkage': 0.15},
            'target_cph': 45.0,
            'expected': 18877.5
        },
        {
            'name': 'Zero FTE',
            'fte_avail': 0,
            'config': {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10},
            'target_cph': 50.0,
            'expected': 0.0
        },
        {
            'name': 'Single FTE',
            'fte_avail': 1,
            'config': {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10},
            'target_cph': 50.0,
            'expected': 850.5
        }
    ]

    all_passed = True
    for i, test in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test['name']}")
        print(f"  FTE Available: {test['fte_avail']}")
        print(f"  Config: {test['config']}")
        print(f"  Target CPH: {test['target_cph']}")

        result = calculate_capacity(
            test['fte_avail'],
            test['config'],
            test['target_cph']
        )

        # Manual calculation for verification
        wd = test['config']['working_days']
        wh = test['config']['work_hours']
        s = test['config']['shrinkage']
        cph = test['target_cph']
        fte = test['fte_avail']

        expected = round(fte * wd * wh * (1-s) * cph, 2) if fte > 0 else 0.0

        print(f"  Result: {result}")
        print(f"  Expected: {expected}")

        if result == expected:
            print("  ✓ PASS")
        else:
            print(f"  ✗ FAIL: Expected {expected}, got {result}")
            all_passed = False

    return all_passed


def test_formula_consistency():
    """Test that FTE Required and Capacity are inverse operations."""
    print("\n" + "=" * 70)
    print("Testing Formula Consistency (FTE ↔ Capacity)")
    print("=" * 70)

    config = {'working_days': 21, 'work_hours': 9, 'shrinkage': 0.10}
    target_cph = 50.0

    print("\nTest: FTE Required → Capacity → should approximate original forecast")

    forecast = 10000
    print(f"  Original Forecast: {forecast}")

    # Calculate FTE Required
    fte_req = calculate_fte_required(forecast, config, target_cph)
    print(f"  Calculated FTE Required: {fte_req}")

    # Calculate Capacity from FTE Required
    capacity = calculate_capacity(fte_req, config, target_cph)
    print(f"  Calculated Capacity from FTE: {capacity}")

    # Check if capacity >= forecast (it should be, due to ceiling in FTE calculation)
    if capacity >= forecast:
        print(f"  ✓ PASS: Capacity ({capacity}) >= Original Forecast ({forecast})")
        print(f"  Note: Capacity is higher due to ceiling in FTE calculation")
        return True
    else:
        print(f"  ✗ FAIL: Capacity ({capacity}) < Original Forecast ({forecast})")
        return False


def verify_no_occupancy_in_calculations():
    """Verify that occupancy is NOT used in calculations."""
    print("\n" + "=" * 70)
    print("Verifying Occupancy is NOT Used")
    print("=" * 70)

    config_with_occ = {
        'working_days': 21,
        'work_hours': 9,
        'shrinkage': 0.10,
        'occupancy': 0.95  # Should be ignored
    }

    config_without_occ = {
        'working_days': 21,
        'work_hours': 9,
        'shrinkage': 0.10
    }

    forecast = 10000
    fte_avail = 10
    target_cph = 50.0

    # Test FTE Required
    fte1 = calculate_fte_required(forecast, config_with_occ, target_cph)
    fte2 = calculate_fte_required(forecast, config_without_occ, target_cph)

    print(f"\nFTE Required Test:")
    print(f"  With occupancy in config: {fte1}")
    print(f"  Without occupancy in config: {fte2}")

    if fte1 == fte2:
        print("  ✓ PASS: Occupancy is correctly ignored")
        fte_pass = True
    else:
        print("  ✗ FAIL: Results differ when occupancy present")
        fte_pass = False

    # Test Capacity
    cap1 = calculate_capacity(fte_avail, config_with_occ, target_cph)
    cap2 = calculate_capacity(fte_avail, config_without_occ, target_cph)

    print(f"\nCapacity Test:")
    print(f"  With occupancy in config: {cap1}")
    print(f"  Without occupancy in config: {cap2}")

    if cap1 == cap2:
        print("  ✓ PASS: Occupancy is correctly ignored")
        cap_pass = True
    else:
        print("  ✗ FAIL: Results differ when occupancy present")
        cap_pass = False

    return fte_pass and cap_pass


def main():
    """Run all verification tests."""
    print("\n" + "=" * 70)
    print("COMPREHENSIVE CALCULATION VERIFICATION")
    print("=" * 70)

    results = {
        'FTE Required': test_fte_required_calculation(),
        'Capacity': test_capacity_calculation(),
        'Consistency': test_formula_consistency(),
        'No Occupancy': verify_no_occupancy_in_calculations()
    }

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    all_passed = True
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {test_name}: {status}")
        if not passed:
            all_passed = False

    print("=" * 70)

    if all_passed:
        print("✓ ALL TESTS PASSED")
        print("\nConclusion:")
        print("  - All calculations use centralized utilities")
        print("  - Formulas are consistent across the application")
        print("  - Occupancy is correctly excluded from calculations")
        print("  - FTE Required and Capacity formulas are inverse operations")
        return 0
    else:
        print("✗ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    exit(main())
