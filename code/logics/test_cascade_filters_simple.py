"""
Simple test runner for cascade filter locality bug fix (no pytest required).
Tests universal Main_LOB behavior.

Run with: python3 code/logics/test_cascade_filters_simple.py
"""
from code.logics.cascade_filters import filter_main_lobs_by_criteria


def test_universal_matches_domestic():
    """Main_LOB without locality should match locality='Domestic' filter."""
    print("Test 1: Universal matches Domestic filter...")
    main_lobs = ["Amisys Medicaid Domestic", "Amisys Medicaid"]
    result = filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", "Domestic")

    assert "Amisys Medicaid Domestic" in result, "Explicit Domestic should match"
    assert "Amisys Medicaid" in result, "Universal Main_LOB should match Domestic filter"
    assert len(result) == 2, f"Expected 2 results, got {len(result)}: {result}"
    print("✅ PASSED")


def test_universal_matches_global():
    """Main_LOB without locality should match locality='Global' filter."""
    print("Test 2: Universal matches Global filter...")
    main_lobs = ["Amisys Medicaid Global", "Amisys Medicaid"]
    result = filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", "Global")

    assert "Amisys Medicaid Global" in result, "Explicit Global should match"
    assert "Amisys Medicaid" in result, "Universal Main_LOB should match Global filter"
    assert len(result) == 2, f"Expected 2 results, got {len(result)}: {result}"
    print("✅ PASSED")


def test_all_localities_includes_universal():
    """locality=None should include all Main_LOBs (regression test)."""
    print("Test 3: All localities includes universal...")
    main_lobs = ["Amisys Medicaid Domestic", "Amisys Medicaid Global", "Amisys Medicaid"]
    result = filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", None)

    assert len(result) == 3, f"Expected 3 results, got {len(result)}: {result}"
    assert "Amisys Medicaid" in result, "Universal should be included in All"
    print("✅ PASSED")


def test_only_universal_main_lobs():
    """When all Main_LOBs lack locality, all should match any filter."""
    print("Test 4: Only universal Main_LOBs...")
    main_lobs = ["Facets OIC Volumes"]
    result = filter_main_lobs_by_criteria(main_lobs, "Facets", "OIC Volumes", "Domestic")

    assert "Facets OIC Volumes" in result, "Universal Main_LOB should match Domestic"
    assert len(result) == 1, f"Expected 1 result, got {len(result)}: {result}"
    print("✅ PASSED")


def test_explicit_locality_must_match():
    """Main_LOB with explicit locality must match the filter exactly."""
    print("Test 5: Explicit locality must match...")
    main_lobs = ["Amisys Medicaid Domestic", "Amisys Medicaid Global"]
    result = filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", "Domestic")

    assert "Amisys Medicaid Domestic" in result, "Domestic should match"
    assert "Amisys Medicaid Global" not in result, "Global shouldn't match Domestic"
    assert len(result) == 1, f"Expected 1 result, got {len(result)}: {result}"
    print("✅ PASSED")


def test_mixed_explicit_and_universal():
    """Test with mix of explicit localities and universal Main_LOBs."""
    print("Test 6: Mixed explicit and universal...")
    main_lobs = [
        "Amisys Medicaid Domestic",
        "Amisys Medicaid Global",
        "Amisys Medicaid"  # Universal
    ]

    # Filter by Domestic
    result_domestic = filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", "Domestic")
    assert len(result_domestic) == 2, f"Expected 2 for Domestic, got {len(result_domestic)}"
    assert "Amisys Medicaid Domestic" in result_domestic
    assert "Amisys Medicaid" in result_domestic
    assert "Amisys Medicaid Global" not in result_domestic

    # Filter by Global
    result_global = filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", "Global")
    assert len(result_global) == 2, f"Expected 2 for Global, got {len(result_global)}"
    assert "Amisys Medicaid Global" in result_global
    assert "Amisys Medicaid" in result_global
    assert "Amisys Medicaid Domestic" not in result_global

    print("✅ PASSED")


def test_case_insensitive():
    """Locality matching should be case-insensitive."""
    print("Test 7: Case insensitive matching...")
    main_lobs = ["Amisys Medicaid DOMESTIC", "Amisys Medicaid"]
    result = filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", "domestic")

    assert len(result) == 2, f"Expected 2 results, got {len(result)}: {result}"
    assert "Amisys Medicaid DOMESTIC" in result
    assert "Amisys Medicaid" in result
    print("✅ PASSED")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Testing Locality Filter Bug Fix")
    print("=" * 60 + "\n")

    tests_run = 0
    tests_passed = 0

    tests = [
        test_universal_matches_domestic,
        test_universal_matches_global,
        test_all_localities_includes_universal,
        test_only_universal_main_lobs,
        test_explicit_locality_must_match,
        test_mixed_explicit_and_universal,
        test_case_insensitive,
    ]

    for test_func in tests:
        tests_run += 1
        try:
            test_func()
            tests_passed += 1
        except AssertionError as e:
            print(f"❌ FAILED: {e}")
        except Exception as e:
            print(f"❌ ERROR: {e}")

    print("\n" + "=" * 60)
    print(f"Results: {tests_passed}/{tests_run} tests passed")
    print("=" * 60)

    if tests_passed == tests_run:
        print("\n✅ All tests PASSED! The fix is working correctly.\n")
        exit(0)
    else:
        print(f"\n❌ {tests_run - tests_passed} test(s) FAILED\n")
        exit(1)
