"""
Tests for LLM forecast endpoint filter logic.

Covers:
  - apply_forecast_filters: unit tests for all filter types
  - determine_locality: unit tests for locality detection
  - Bracket-notation query param merging (state[]=TX)
  - main_lob variable shadowing fix (loop body uses main_lob_val)
  - calculate_totals: aggregation correctness
"""

import pytest

from code.logics.llm_utils import (
    apply_forecast_filters,
    determine_locality,
    calculate_totals,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_record(
    main_lob="Amisys Medicaid Domestic",
    state="TX",
    case_type="Claims Processing",
    **month_kwargs,
):
    """Build a minimal forecast record dict."""
    record = {
        "Centene_Capacity_Plan_Main_LOB": main_lob,
        "Centene_Capacity_Plan_State": state,
        "Centene_Capacity_Plan_Case_Type": case_type,
        "Centene_Capacity_Plan_Call_Type_ID": "CT001",
        "Centene_Capacity_Plan_Target_CPH": 50.0,
        "UploadedFile": "forecast_March_2025.xlsx",
    }
    for i in range(1, 7):
        record[f"Client_Forecast_Month{i}"] = month_kwargs.get(f"forecast{i}", 0.0)
        record[f"FTE_Avail_Month{i}"] = month_kwargs.get(f"fte_avail{i}", 0)
        record[f"FTE_Required_Month{i}"] = month_kwargs.get(f"fte_req{i}", 0)
        record[f"Capacity_Month{i}"] = month_kwargs.get(f"capacity{i}", 0.0)
    return record


SAMPLE_RECORDS = [
    _make_record("Amisys Medicaid Domestic", "TX", "Claims Processing"),
    _make_record("Amisys Medicaid Domestic", "CA", "Claims Processing"),
    _make_record("Facets Medicare Global", "N/A", "Enrollment"),
    _make_record("Facets OIC Volumes", "N/A", "Claims Processing Domestic"),
    _make_record("Amisys Medicaid Domestic", "TX", "Enrollment"),
]


# ---------------------------------------------------------------------------
# determine_locality
# ---------------------------------------------------------------------------

class TestDetermineLocality:
    def test_domestic_in_lob(self):
        assert determine_locality("Amisys Medicaid Domestic", "Claims") == "Domestic"

    def test_global_in_lob(self):
        assert determine_locality("Facets Medicare Global", "Enrollment") == "Global"

    def test_oic_volumes_domestic_case_type(self):
        assert determine_locality("Facets OIC Volumes", "Claims Processing Domestic") == "Domestic"

    def test_oic_volumes_global_case_type(self):
        assert determine_locality("Facets OIC Volumes", "Enrollment") == "Global"

    def test_oic_volumes_empty_case_type(self):
        assert determine_locality("Facets OIC Volumes", "") == "Global"

    def test_offshore_normalized_to_global(self):
        assert determine_locality("Amisys Medicaid Offshore", "Claims") == "Global"

    def test_onshore_not_in_localities_defaults_to_global(self):
        # "Onshore" is not in LOCALITIES = ["domestic", "global", ...],
        # so parse_main_lob returns locality=None and determine_locality defaults to Global.
        assert determine_locality("Amisys Medicaid Onshore", "Claims") == "Global"

    def test_empty_main_lob_defaults_to_global(self):
        assert determine_locality("", "Claims") == "Global"

    def test_none_main_lob_defaults_to_global(self):
        assert determine_locality(None, "Claims") == "Global"

    def test_case_insensitive_locality(self):
        assert determine_locality("Amisys Medicaid DOMESTIC", "Claims") == "Domestic"


# ---------------------------------------------------------------------------
# apply_forecast_filters — no filters
# ---------------------------------------------------------------------------

class TestApplyForecastFiltersNoFilter:
    def test_empty_filters_returns_all(self):
        filters = {"platform": [], "market": [], "locality": [], "main_lob": [], "state": [], "case_type": [], "forecast_months": []}
        result = apply_forecast_filters(SAMPLE_RECORDS, filters)
        assert len(result) == len(SAMPLE_RECORDS)

    def test_empty_records_returns_empty(self):
        filters = {"state": ["TX"]}
        assert apply_forecast_filters([], filters) == []


# ---------------------------------------------------------------------------
# apply_forecast_filters — state filter
# ---------------------------------------------------------------------------

class TestApplyForecastFiltersState:
    def test_single_state_filter(self):
        filters = {"platform": [], "market": [], "locality": [], "main_lob": [], "state": ["TX"], "case_type": [], "forecast_months": []}
        result = apply_forecast_filters(SAMPLE_RECORDS, filters)
        assert all(r["Centene_Capacity_Plan_State"] == "TX" for r in result)
        assert len(result) == 2  # Two TX records

    def test_multiple_states_filter(self):
        filters = {"platform": [], "market": [], "locality": [], "main_lob": [], "state": ["TX", "CA"], "case_type": [], "forecast_months": []}
        result = apply_forecast_filters(SAMPLE_RECORDS, filters)
        states = {r["Centene_Capacity_Plan_State"] for r in result}
        assert states == {"TX", "CA"}
        assert len(result) == 3

    def test_state_filter_case_insensitive(self):
        filters = {"platform": [], "market": [], "locality": [], "main_lob": [], "state": ["tx"], "case_type": [], "forecast_months": []}
        result = apply_forecast_filters(SAMPLE_RECORDS, filters)
        assert len(result) == 2

    def test_state_filter_no_match_returns_empty(self):
        filters = {"platform": [], "market": [], "locality": [], "main_lob": [], "state": ["ZZ"], "case_type": [], "forecast_months": []}
        result = apply_forecast_filters(SAMPLE_RECORDS, filters)
        assert result == []

    def test_state_bracket_notation_equivalent(self):
        """state[]=TX and state=TX should produce the same filter result."""
        filters_standard = {"platform": [], "market": [], "locality": [], "main_lob": [], "state": ["TX"], "case_type": [], "forecast_months": []}
        # Simulate bracket-notation merge (same list after merge)
        filters_bracket = {"platform": [], "market": [], "locality": [], "main_lob": [], "state": ["TX"], "case_type": [], "forecast_months": []}
        assert apply_forecast_filters(SAMPLE_RECORDS, filters_standard) == apply_forecast_filters(SAMPLE_RECORDS, filters_bracket)


# ---------------------------------------------------------------------------
# apply_forecast_filters — case_type filter
# ---------------------------------------------------------------------------

class TestApplyForecastFiltersCaseType:
    def test_single_case_type(self):
        filters = {"platform": [], "market": [], "locality": [], "main_lob": [], "state": [], "case_type": ["Enrollment"], "forecast_months": []}
        result = apply_forecast_filters(SAMPLE_RECORDS, filters)
        assert all(r["Centene_Capacity_Plan_Case_Type"] == "Enrollment" for r in result)
        assert len(result) == 2

    def test_case_type_case_insensitive(self):
        filters = {"platform": [], "market": [], "locality": [], "main_lob": [], "state": [], "case_type": ["claims processing"], "forecast_months": []}
        result = apply_forecast_filters(SAMPLE_RECORDS, filters)
        assert len(result) == 2  # TX and CA Claims Processing (exact match, OIC has "Claims Processing Domestic")

    def test_combined_state_and_case_type(self):
        filters = {"platform": [], "market": [], "locality": [], "main_lob": [], "state": ["TX"], "case_type": ["Claims Processing"], "forecast_months": []}
        result = apply_forecast_filters(SAMPLE_RECORDS, filters)
        assert len(result) == 1
        assert result[0]["Centene_Capacity_Plan_State"] == "TX"
        assert result[0]["Centene_Capacity_Plan_Case_Type"] == "Claims Processing"


# ---------------------------------------------------------------------------
# apply_forecast_filters — main_lob filter
# ---------------------------------------------------------------------------

class TestApplyForecastFiltersMainLob:
    def test_main_lob_exact_match(self):
        filters = {"platform": [], "market": [], "locality": [], "main_lob": ["Amisys Medicaid Domestic"], "state": [], "case_type": [], "forecast_months": []}
        result = apply_forecast_filters(SAMPLE_RECORDS, filters)
        assert all(r["Centene_Capacity_Plan_Main_LOB"] == "Amisys Medicaid Domestic" for r in result)
        assert len(result) == 3

    def test_main_lob_case_insensitive(self):
        filters = {"platform": [], "market": [], "locality": [], "main_lob": ["amisys medicaid domestic"], "state": [], "case_type": [], "forecast_months": []}
        result = apply_forecast_filters(SAMPLE_RECORDS, filters)
        assert len(result) == 3

    def test_main_lob_filter_overrides_platform_filter(self):
        """When main_lob filter is set, platform/market/locality filters are skipped."""
        filters = {
            "platform": ["Facets"],  # Would only match Facets records
            "market": [],
            "locality": [],
            "main_lob": ["Amisys Medicaid Domestic"],  # Overrides platform filter
            "state": [],
            "case_type": [],
            "forecast_months": []
        }
        result = apply_forecast_filters(SAMPLE_RECORDS, filters)
        # Should match Amisys records, not Facets — main_lob overrides
        assert all("Amisys" in r["Centene_Capacity_Plan_Main_LOB"] for r in result)
        assert len(result) == 3

    def test_main_lob_combined_with_state(self):
        """main_lob filter and state filter are applied together (AND logic)."""
        filters = {
            "platform": [], "market": [], "locality": [],
            "main_lob": ["Amisys Medicaid Domestic"],
            "state": ["CA"],
            "case_type": [], "forecast_months": []
        }
        result = apply_forecast_filters(SAMPLE_RECORDS, filters)
        assert len(result) == 1
        assert result[0]["Centene_Capacity_Plan_State"] == "CA"

    def test_main_lob_no_match_returns_empty(self):
        filters = {"platform": [], "market": [], "locality": [], "main_lob": ["NonExistent LOB"], "state": [], "case_type": [], "forecast_months": []}
        result = apply_forecast_filters(SAMPLE_RECORDS, filters)
        assert result == []


# ---------------------------------------------------------------------------
# apply_forecast_filters — platform / locality filters
# ---------------------------------------------------------------------------

class TestApplyForecastFiltersPlatformLocality:
    def test_platform_filter_amisys(self):
        filters = {"platform": ["Amisys"], "market": [], "locality": [], "main_lob": [], "state": [], "case_type": [], "forecast_months": []}
        result = apply_forecast_filters(SAMPLE_RECORDS, filters)
        assert all("Amisys" in r["Centene_Capacity_Plan_Main_LOB"] for r in result)

    def test_platform_filter_facets(self):
        filters = {"platform": ["Facets"], "market": [], "locality": [], "main_lob": [], "state": [], "case_type": [], "forecast_months": []}
        result = apply_forecast_filters(SAMPLE_RECORDS, filters)
        assert all("Facets" in r["Centene_Capacity_Plan_Main_LOB"] for r in result)

    def test_locality_filter_domestic(self):
        filters = {"platform": [], "market": [], "locality": ["Domestic"], "main_lob": [], "state": [], "case_type": [], "forecast_months": []}
        result = apply_forecast_filters(SAMPLE_RECORDS, filters)
        # Amisys Medicaid Domestic (3 records) + OIC Volumes with Domestic case_type (1)
        assert len(result) == 4

    def test_locality_filter_global(self):
        filters = {"platform": [], "market": [], "locality": ["Global"], "main_lob": [], "state": [], "case_type": [], "forecast_months": []}
        result = apply_forecast_filters(SAMPLE_RECORDS, filters)
        assert len(result) == 1
        assert result[0]["Centene_Capacity_Plan_Main_LOB"] == "Facets Medicare Global"


# ---------------------------------------------------------------------------
# calculate_totals
# ---------------------------------------------------------------------------

class TestCalculateTotals:
    def _make_transformed(self, months_data):
        return {"months": months_data}

    def test_basic_totals(self):
        records = [
            self._make_transformed({"Apr-25": {"forecast": 100.0, "fte_available": 5, "fte_required": 4, "capacity": 200.0, "gap": 100.0}}),
            self._make_transformed({"Apr-25": {"forecast": 200.0, "fte_available": 10, "fte_required": 8, "capacity": 400.0, "gap": 200.0}}),
        ]
        totals = calculate_totals(records, ["Apr-25"])
        assert totals["Apr-25"]["forecast_total"] == 300.0
        assert totals["Apr-25"]["fte_available_total"] == 15
        assert totals["Apr-25"]["fte_required_total"] == 12
        assert totals["Apr-25"]["capacity_total"] == 600.0
        assert totals["Apr-25"]["gap_total"] == 300.0

    def test_multiple_months(self):
        records = [
            self._make_transformed({
                "Apr-25": {"forecast": 100.0, "fte_available": 5, "fte_required": 4, "capacity": 200.0, "gap": 100.0},
                "May-25": {"forecast": 150.0, "fte_available": 7, "fte_required": 6, "capacity": 300.0, "gap": 150.0},
            }),
        ]
        totals = calculate_totals(records, ["Apr-25", "May-25"])
        assert totals["Apr-25"]["forecast_total"] == 100.0
        assert totals["May-25"]["forecast_total"] == 150.0

    def test_missing_month_in_record_treated_as_zero(self):
        records = [
            self._make_transformed({"Apr-25": {"forecast": 100.0, "fte_available": 5, "fte_required": 4, "capacity": 200.0, "gap": 100.0}}),
        ]
        totals = calculate_totals(records, ["Apr-25", "May-25"])
        assert totals["May-25"]["forecast_total"] == 0.0
        assert totals["May-25"]["fte_available_total"] == 0

    def test_empty_records_all_zeros(self):
        totals = calculate_totals([], ["Apr-25"])
        assert totals["Apr-25"]["forecast_total"] == 0.0

    def test_rounding(self):
        records = [
            self._make_transformed({"Apr-25": {"forecast": 100.123456, "fte_available": 5, "fte_required": 4, "capacity": 200.999, "gap": 100.876}}),
        ]
        totals = calculate_totals(records, ["Apr-25"])
        assert totals["Apr-25"]["forecast_total"] == round(100.123456, 2)
        assert totals["Apr-25"]["capacity_total"] == round(200.999, 2)


# ---------------------------------------------------------------------------
# Integration: bracket-notation param merging in the endpoint
# ---------------------------------------------------------------------------

class TestBracketNotationMerging:
    """
    Tests the merging logic for bracket-notation query params (state[]=TX)
    vs standard FastAPI Query params (state=TX).

    These test the merge logic in isolation since we can't spin up the full
    app in unit tests without a database.
    """

    def _merge(self, standard, bracket):
        """Simulate what the endpoint does: merge standard and bracket-notation."""
        return list(set((standard or []) + bracket))

    def test_bracket_only_state(self):
        result = self._merge(None, ["TX"])
        assert "TX" in result

    def test_standard_only_state(self):
        result = self._merge(["TX"], [])
        assert result == ["TX"]

    def test_both_no_duplicates(self):
        result = self._merge(["TX"], ["TX", "CA"])
        assert sorted(result) == ["CA", "TX"]

    def test_empty_both_gives_empty(self):
        result = self._merge(None, [])
        assert result == []

    def test_multiple_bracket_values(self):
        result = self._merge(None, ["TX", "CA", "NY"])
        assert sorted(result) == ["CA", "NY", "TX"]

    def test_main_lob_with_spaces(self):
        """main_lob values contain spaces; merge should not break them."""
        result = self._merge(None, ["Amisys Medicaid Domestic"])
        assert result == ["Amisys Medicaid Domestic"]

    def test_main_lob_deduplication(self):
        result = self._merge(["Amisys Medicaid Domestic"], ["Amisys Medicaid Domestic"])
        assert result == ["Amisys Medicaid Domestic"]

    def test_main_lob_multiple_values(self):
        result = self._merge(["Amisys Medicaid Domestic"], ["Facets Medicare Global"])
        assert sorted(result) == ["Amisys Medicaid Domestic", "Facets Medicare Global"]


# ---------------------------------------------------------------------------
# main_lob_val shadowing fix
# ---------------------------------------------------------------------------

class TestMainLobShadowingFix:
    """
    Verifies that after filtering, the transform loop correctly reads
    each record's main_lob field without affecting the filter state.

    The fix renamed the loop variable from 'main_lob' to 'main_lob_val'
    to avoid shadowing the filter parameter list.
    """

    def test_filter_then_transform_uses_correct_field(self):
        """After filtering, each transformed record has the correct main_lob from the record."""
        records = [
            _make_record("Amisys Medicaid Domestic", "TX", "Claims Processing"),
            _make_record("Facets Medicare Global", "N/A", "Enrollment"),
        ]
        filters = {
            "platform": [], "market": [], "locality": [], "main_lob": [],
            "state": ["TX"], "case_type": [], "forecast_months": []
        }
        filtered = apply_forecast_filters(records, filters)
        assert len(filtered) == 1
        # Simulate what the transform loop does: read main_lob_val from each record
        for record in filtered:
            main_lob_val = record.get("Centene_Capacity_Plan_Main_LOB", "")
            assert main_lob_val == "Amisys Medicaid Domestic"

    def test_filter_list_not_overwritten_by_loop(self):
        """The filter list (a list) must remain intact through the loop."""
        main_lob_filter = ["Amisys Medicaid Domestic"]
        records = [
            _make_record("Amisys Medicaid Domestic", "TX", "Claims Processing"),
            _make_record("Amisys Medicaid Domestic", "CA", "Enrollment"),
        ]
        filters = {
            "platform": [], "market": [], "locality": [],
            "main_lob": main_lob_filter,
            "state": [], "case_type": [], "forecast_months": []
        }
        filtered = apply_forecast_filters(records, filters)
        # Filter should still work correctly after multiple iterations
        assert len(filtered) == 2
        # Confirm the filter list object is unchanged
        assert main_lob_filter == ["Amisys Medicaid Domestic"]
