"""
Test suite for cascade filter locality bug fix.
Tests universal Main_LOB behavior (Main_LOBs without explicit locality).

This test suite verifies that Main_LOBs without explicit locality suffix
(e.g., "Amisys Medicaid", "Facets OIC Volumes") are treated as "universal"
and match ANY locality filter (Domestic, Global, or All).

Run with: python3 -m pytest code/logics/test_cascade_filters.py -v
"""
import pytest
from code.logics.cascade_filters import filter_main_lobs_by_criteria


class TestUniversalLocalityFiltering:
    """Test Main_LOBs without locality (universal types) match any locality filter."""

    def test_universal_matches_domestic(self):
        """Main_LOB without locality should match locality='Domestic' filter."""
        main_lobs = ["Amisys Medicaid Domestic", "Amisys Medicaid"]
        result = filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", "Domestic")

        assert "Amisys Medicaid Domestic" in result, "Explicit Domestic should match"
        assert "Amisys Medicaid" in result, "Universal Main_LOB should match Domestic filter"
        assert len(result) == 2, "Should include both explicit and universal"

    def test_universal_matches_global(self):
        """Main_LOB without locality should match locality='Global' filter."""
        main_lobs = ["Amisys Medicaid Global", "Amisys Medicaid"]
        result = filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", "Global")

        assert "Amisys Medicaid Global" in result, "Explicit Global should match"
        assert "Amisys Medicaid" in result, "Universal Main_LOB should match Global filter"
        assert len(result) == 2, "Should include both explicit and universal"

    def test_all_localities_includes_universal(self):
        """locality=None should include all Main_LOBs (regression test)."""
        main_lobs = ["Amisys Medicaid Domestic", "Amisys Medicaid Global", "Amisys Medicaid"]
        result = filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", None)

        assert len(result) == 3, "All Localities should return all Main_LOBs"
        assert "Amisys Medicaid Domestic" in result
        assert "Amisys Medicaid Global" in result
        assert "Amisys Medicaid" in result, "Universal should be included in All"

    def test_only_universal_main_lobs_domestic(self):
        """When all Main_LOBs lack locality, all should match Domestic filter."""
        main_lobs = ["Facets OIC Volumes"]
        result = filter_main_lobs_by_criteria(main_lobs, "Facets", "OIC Volumes", "Domestic")

        assert "Facets OIC Volumes" in result, "Universal Main_LOB should match Domestic"
        assert len(result) == 1, "Should include the universal Main_LOB"

    def test_only_universal_main_lobs_global(self):
        """When all Main_LOBs lack locality, all should match Global filter."""
        main_lobs = ["Facets OIC Volumes"]
        result = filter_main_lobs_by_criteria(main_lobs, "Facets", "OIC Volumes", "Global")

        assert "Facets OIC Volumes" in result, "Universal Main_LOB should match Global"
        assert len(result) == 1, "Should include the universal Main_LOB"

    def test_explicit_locality_must_match(self):
        """Main_LOB with explicit locality must match the filter exactly."""
        main_lobs = ["Amisys Medicaid Domestic", "Amisys Medicaid Global"]
        result = filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", "Domestic")

        assert "Amisys Medicaid Domestic" in result, "Domestic should match Domestic filter"
        assert "Amisys Medicaid Global" not in result, "Global shouldn't match Domestic filter"
        assert len(result) == 1, "Should only include matching locality"

    def test_case_insensitive_locality(self):
        """Locality matching should be case-insensitive."""
        main_lobs = ["Amisys Medicaid DOMESTIC", "Amisys Medicaid"]
        result = filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", "domestic")

        assert len(result) == 2, "Both explicit (uppercase) and universal should match"
        assert "Amisys Medicaid DOMESTIC" in result
        assert "Amisys Medicaid" in result

    def test_universal_respects_platform_market(self):
        """Universal Main_LOBs still must match platform and market."""
        main_lobs = ["Amisys Medicaid", "Facets Medicare"]
        result = filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", "Domestic")

        assert "Amisys Medicaid" in result, "Should include universal with matching platform/market"
        assert "Facets Medicare" not in result, "Wrong platform should be excluded"
        assert len(result) == 1, "Should only include matching platform/market"

    def test_mixed_explicit_and_universal(self):
        """Test with mix of explicit localities and universal Main_LOBs."""
        main_lobs = [
            "Amisys Medicaid Domestic",
            "Amisys Medicaid Global",
            "Amisys Medicaid"  # Universal
        ]

        # Filter by Domestic - should include Domestic + universal
        result_domestic = filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", "Domestic")
        assert len(result_domestic) == 2
        assert "Amisys Medicaid Domestic" in result_domestic
        assert "Amisys Medicaid" in result_domestic
        assert "Amisys Medicaid Global" not in result_domestic

        # Filter by Global - should include Global + universal
        result_global = filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", "Global")
        assert len(result_global) == 2
        assert "Amisys Medicaid Global" in result_global
        assert "Amisys Medicaid" in result_global
        assert "Amisys Medicaid Domestic" not in result_global

    def test_multiple_universal_main_lobs(self):
        """Test with multiple universal Main_LOBs."""
        main_lobs = ["Facets OIC Volumes", "Facets Projects", "Facets Medicare Domestic"]
        result = filter_main_lobs_by_criteria(main_lobs, "Facets", "OIC Volumes", "Domestic")

        assert "Facets OIC Volumes" in result, "Should include matching universal"
        assert "Facets Projects" not in result, "Wrong market should be excluded"
        assert "Facets Medicare Domestic" not in result, "Wrong market should be excluded"
        assert len(result) == 1, "Should only include OIC Volumes"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_main_lobs_list(self):
        """Test with empty Main_LOBs list."""
        result = filter_main_lobs_by_criteria([], "Amisys", "Medicaid", "Domestic")
        assert result == [], "Should return empty list"

    def test_no_matches(self):
        """Test when no Main_LOBs match the criteria."""
        main_lobs = ["Facets Medicare Global"]
        result = filter_main_lobs_by_criteria(main_lobs, "Amisys", "Medicaid", "Domestic")
        assert result == [], "Should return empty list when no matches"

    def test_invalid_platform_filter(self):
        """Test that invalid platform filter raises ValueError."""
        main_lobs = ["Amisys Medicaid Domestic"]

        with pytest.raises(ValueError, match="platform_filter cannot be"):
            filter_main_lobs_by_criteria(main_lobs, "", "Medicaid", "Domestic")

        with pytest.raises(ValueError, match="platform_filter cannot be"):
            filter_main_lobs_by_criteria(main_lobs, None, "Medicaid", "Domestic")

    def test_invalid_market_filter(self):
        """Test that invalid market filter raises ValueError."""
        main_lobs = ["Amisys Medicaid Domestic"]

        with pytest.raises(ValueError, match="market_filter cannot be"):
            filter_main_lobs_by_criteria(main_lobs, "Amisys", "", "Domestic")

        with pytest.raises(ValueError, match="market_filter cannot be"):
            filter_main_lobs_by_criteria(main_lobs, "Amisys", None, "Domestic")


if __name__ == "__main__":
    # Allow running tests directly with: python3 code/logics/test_cascade_filters.py
    pytest.main([__file__, "-v"])
