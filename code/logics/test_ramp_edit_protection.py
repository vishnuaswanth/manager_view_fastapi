"""
Tests for ramp-aware FTE and CPH edit protection.

Covers:
  1. _month_label_to_key — label → "YYYY-MM" key conversion (inverse of _parse_month_key_to_label)
  2. get_ramp_contribution_for_month — DB-backed ramp FTE/capacity query
  3. FTE reallocation ramp floor protection (HTTPException 400 when reduction exceeds base FTEs)
  4. Capacity split in FTE reallocation (base formula + ramp_capacity)
  5. CPH preview ramp-aware capacity split
  6. CPH apply ramp-aware capacity split

Run with:
    python3 -m pytest code/logics/test_ramp_edit_protection.py -v
"""

import math
import pytest
from unittest.mock import MagicMock, patch, call
from fastapi import HTTPException


# ============================================================================
# SHARED TEST HELPERS
# ============================================================================

# Standard months dict matching a "January 2026" report period
MONTHS_DICT = {
    "month1": "Jan-26",
    "month2": "Feb-26",
    "month3": "Mar-26",
    "month4": "Apr-26",
    "month5": "May-26",
    "month6": "Jun-26",
}

# Standard month config (domestic)
STD_CONFIG = {
    "working_days": 21,
    "work_hours": 9.0,
    "shrinkage": 0.10,
    "occupancy": 0.95,
}

# 6-month config dict (month1..month6 all using STD_CONFIG)
SIX_MONTH_CONFIG = {f"month{i}": STD_CONFIG.copy() for i in range(1, 7)}


def make_session_mock(query_result):
    """Context-manager-compatible session that returns query_result from .all()."""
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    session.query.return_value.filter.return_value.all.return_value = query_result
    return session


def make_core_utils_mock(session_mock):
    """CoreUtils mock whose db_manager returns session_mock."""
    db = MagicMock()
    db.SessionLocal.return_value = session_mock
    cu = MagicMock()
    cu.get_db_manager.return_value = db
    return cu


def make_forecast_row(
    main_lob="Amisys",
    state="CA",
    case_type="Claims",
    target_cph=10.0,
    forecast_id=42,
    fte_avail=27,
    capacity=2000,
    forecast=1000,
    fte_req=15,
):
    """Mock ForecastModel with all 6 month columns set uniformly."""
    row = MagicMock()
    row.id = forecast_id
    row.Centene_Capacity_Plan_Main_LOB = main_lob
    row.Centene_Capacity_Plan_State = state
    row.Centene_Capacity_Plan_Case_Type = case_type
    row.Centene_Capacity_Plan_Target_CPH = target_cph
    row.Centene_Capacity_Plan_Call_Type_ID = "CASE-123"
    row.Month = "January"
    row.Year = 2026
    for i in range(1, 7):
        setattr(row, f"FTE_Avail_Month{i}", fte_avail)
        setattr(row, f"Capacity_Month{i}", capacity)
        setattr(row, f"Client_Forecast_Month{i}", forecast)
        setattr(row, f"FTE_Required_Month{i}", fte_req)
    return row


def make_realloc_input(main_lob="Amisys", state="CA", case_type="Claims",
                       month_overrides=None):
    """
    Build a modified_records entry with all 6 months unchanged by default.
    Use month_overrides to set specific {month_label: {fte_avail, fte_avail_change}} entries.
    """
    months = {label: {"fte_avail": 27, "fte_avail_change": 0}
              for label in MONTHS_DICT.values()}
    if month_overrides:
        months.update(month_overrides)
    return {
        "main_lob": main_lob,
        "state": state,
        "case_type": case_type,
        "target_cph_change": 0,
        "months": months,
    }


def expected_capacity(fte_avail, config=STD_CONFIG, cph=10.0):
    """Calculate the expected capacity using the standard formula (floored)."""
    cap = fte_avail * config["working_days"] * config["work_hours"] * (1 - config["shrinkage"]) * cph
    return int(math.floor(cap))


def make_ramp_row(ramp_name="Ramp-A", employee_count=9, ramp_percent=100.0, working_days=5):
    """Mock RampModel row."""
    row = MagicMock()
    row.ramp_name = ramp_name
    row.employee_count = employee_count
    row.ramp_percent = ramp_percent
    row.working_days = working_days
    return row


# ============================================================================
# 1. _month_label_to_key — pure conversion helper
# ============================================================================


class TestMonthLabelToKey:
    """
    Tests for _month_label_to_key: 'Mon-YY' → 'YYYY-MM'.
    This is the exact inverse of the existing _parse_month_key_to_label.
    """

    def _call(self, month_label: str) -> str:
        from code.logics.ramp_calculator import _month_label_to_key
        return _month_label_to_key(month_label)

    def test_january_2026(self):
        assert self._call("Jan-26") == "2026-01"

    def test_december_2025(self):
        assert self._call("Dec-25") == "2025-12"

    def test_june_2025(self):
        assert self._call("Jun-25") == "2025-06"

    def test_march_2026(self):
        assert self._call("Mar-26") == "2026-03"

    def test_october_2027(self):
        assert self._call("Oct-27") == "2027-10"

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            self._call("January-2026")

    def test_roundtrip_with_parse_month_key_to_label(self):
        """Composing both functions must return the original key."""
        from code.logics.ramp_calculator import _parse_month_key_to_label, _month_label_to_key
        for key in ["2026-01", "2025-12", "2026-06", "2026-03"]:
            label = _parse_month_key_to_label(key)
            assert _month_label_to_key(label) == key


# ============================================================================
# 2. get_ramp_contribution_for_month — DB-backed unit tests
# ============================================================================


class TestGetRampContributionForMonth:
    """Tests for get_ramp_contribution_for_month with mocked DB."""

    def _make_ramp_db(self, mock_cu, ramp_rows):
        """Wire mock_cu so get_db_manager returns a session yielding ramp_rows."""
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        session.query.return_value.filter.return_value.all.return_value = ramp_rows
        db = MagicMock()
        db.SessionLocal.return_value = session
        mock_cu.get_db_manager.return_value = db

    @patch("code.logics.ramp_calculator.core_utils")
    def test_no_ramp_rows_returns_zero_tuple(self, mock_cu):
        """When no RampModel rows exist, returns (0, 0.0)."""
        self._make_ramp_db(mock_cu, [])
        from code.logics.ramp_calculator import get_ramp_contribution_for_month
        ramp_fte, ramp_cap = get_ramp_contribution_for_month(42, "2026-01", 10.0, STD_CONFIG)
        assert ramp_fte == 0
        assert ramp_cap == 0.0

    @patch("code.logics.ramp_calculator.core_utils")
    def test_single_row_ramp_fte_is_employee_count(self, mock_cu):
        """Single ramp row: ramp_fte = employee_count (max of one-element list)."""
        self._make_ramp_db(mock_cu, [make_ramp_row(employee_count=9)])
        from code.logics.ramp_calculator import get_ramp_contribution_for_month
        ramp_fte, _ = get_ramp_contribution_for_month(42, "2026-01", 10.0, STD_CONFIG)
        assert ramp_fte == 9

    @patch("code.logics.ramp_calculator.core_utils")
    def test_single_row_capacity_formula(self, mock_cu):
        """
        Single row: ramp_capacity = employee_count × (ramp_percent/100) × cph
                    × work_hours × (1-shrinkage) × working_days
        With employee_count=9, ramp_percent=100, cph=10, work_hours=9, shrinkage=0.10, wd=5:
        = 9 × 1.0 × 10 × 9 × 0.90 × 5 = 3645.0
        """
        self._make_ramp_db(mock_cu, [make_ramp_row(employee_count=9, ramp_percent=100.0, working_days=5)])
        from code.logics.ramp_calculator import get_ramp_contribution_for_month
        _, ramp_cap = get_ramp_contribution_for_month(42, "2026-01", 10.0, STD_CONFIG)
        expected = 9 * (100 / 100) * 10.0 * 9.0 * (1 - 0.10) * 5
        assert abs(ramp_cap - expected) < 0.001

    @patch("code.logics.ramp_calculator.core_utils")
    def test_two_ramp_names_ramp_fte_is_sum_of_maxes(self, mock_cu):
        """
        Two ramp names (A: max=9, B: max=5) → ramp_fte = 9 + 5 = 14.
        ramp_fte is the sum of max(employee_count) per ramp_name group.
        """
        rows = [
            make_ramp_row("Ramp-A", employee_count=9),
            make_ramp_row("Ramp-B", employee_count=5),
        ]
        self._make_ramp_db(mock_cu, rows)
        from code.logics.ramp_calculator import get_ramp_contribution_for_month
        ramp_fte, _ = get_ramp_contribution_for_month(42, "2026-01", 10.0, STD_CONFIG)
        assert ramp_fte == 14  # max(9) + max(5)

    @patch("code.logics.ramp_calculator.core_utils")
    def test_same_ramp_name_multiple_rows_max_employee_count(self, mock_cu):
        """
        Two rows with same ramp_name (week 1: 5 emps, week 2: 9 emps) →
        ramp_fte = max(5, 9) = 9.
        """
        rows = [
            make_ramp_row("Ramp-A", employee_count=5),
            make_ramp_row("Ramp-A", employee_count=9),
        ]
        self._make_ramp_db(mock_cu, rows)
        from code.logics.ramp_calculator import get_ramp_contribution_for_month
        ramp_fte, _ = get_ramp_contribution_for_month(42, "2026-01", 10.0, STD_CONFIG)
        assert ramp_fte == 9

    @patch("code.logics.ramp_calculator.core_utils")
    def test_ramp_capacity_sums_all_rows(self, mock_cu):
        """Capacity is summed across all rows (regardless of ramp_name)."""
        rows = [
            make_ramp_row("Ramp-A", employee_count=5, ramp_percent=100.0, working_days=5),
            make_ramp_row("Ramp-B", employee_count=3, ramp_percent=50.0, working_days=3),
        ]
        self._make_ramp_db(mock_cu, rows)
        from code.logics.ramp_calculator import get_ramp_contribution_for_month
        _, ramp_cap = get_ramp_contribution_for_month(42, "2026-01", 10.0, STD_CONFIG)
        row_a = 5 * (100 / 100) * 10.0 * 9.0 * 0.90 * 5   # 2025.0
        row_b = 3 * (50 / 100) * 10.0 * 9.0 * 0.90 * 3    # 364.5
        assert abs(ramp_cap - (row_a + row_b)) < 0.001

    @patch("code.logics.ramp_calculator.core_utils")
    def test_ramp_fte_does_not_depend_on_cph(self, mock_cu):
        """ramp_fte (headcount) is independent of target_cph."""
        self._make_ramp_db(mock_cu, [make_ramp_row(employee_count=9)])
        from code.logics.ramp_calculator import get_ramp_contribution_for_month
        ramp_fte_low_cph, _ = get_ramp_contribution_for_month(42, "2026-01", 5.0, STD_CONFIG)
        # Reset the session mock so it returns the same row again
        self._make_ramp_db(mock_cu, [make_ramp_row(employee_count=9)])
        ramp_fte_high_cph, _ = get_ramp_contribution_for_month(42, "2026-01", 100.0, STD_CONFIG)
        assert ramp_fte_low_cph == ramp_fte_high_cph == 9


# ============================================================================
# 3. FTE Reallocation — ramp floor protection
# ============================================================================


class TestFTERampFloorProtection:
    """
    Tests for the ramp floor validation inside calculate_reallocation_preview (Step 4).

    Business rule: FTE reductions can only come from base (non-ramp) FTEs.
    When new_fte_avail < ramp_fte → HTTPException 400.
    """

    @staticmethod
    def _run_preview(mock_months, mock_work_type, mock_config, mock_ramp,
                     input_rec, fte_avail=27, capacity=2000):
        """Helper that wires all mocks and calls calculate_reallocation_preview."""
        mock_months.return_value = MONTHS_DICT
        mock_work_type.return_value = "Domestic"
        mock_config.return_value = SIX_MONTH_CONFIG

        db_rec = make_forecast_row(fte_avail=fte_avail, capacity=capacity)
        session = make_session_mock([db_rec])
        cu = make_core_utils_mock(session)

        from code.logics.forecast_reallocation_transformer import calculate_reallocation_preview
        return calculate_reallocation_preview("January", 2026, [input_rec], cu)

    @patch("code.logics.forecast_reallocation_transformer.get_ramp_contribution_for_month")
    @patch("code.logics.forecast_reallocation_transformer.get_month_config_for_forecast")
    @patch("code.logics.forecast_reallocation_transformer._get_work_type_from_main_lob")
    @patch("code.logics.forecast_reallocation_transformer.get_months_dict")
    def test_no_ramp_any_reduction_passes(
        self, mock_months, mock_work_type, mock_config, mock_ramp
    ):
        """When ramp_fte=0 (no ramp), any reduction is allowed."""
        mock_ramp.return_value = (0, 0.0)
        # Reduce from 27 → 1 (very aggressive reduction)
        rec = make_realloc_input(
            month_overrides={"Jan-26": {"fte_avail": 1, "fte_avail_change": -26}}
        )
        # Should NOT raise
        result = self._run_preview(mock_months, mock_work_type, mock_config, mock_ramp, rec)
        assert result.success is True

    @patch("code.logics.forecast_reallocation_transformer.get_ramp_contribution_for_month")
    @patch("code.logics.forecast_reallocation_transformer.get_month_config_for_forecast")
    @patch("code.logics.forecast_reallocation_transformer._get_work_type_from_main_lob")
    @patch("code.logics.forecast_reallocation_transformer.get_months_dict")
    def test_ramp_active_reduction_within_base_succeeds(
        self, mock_months, mock_work_type, mock_config, mock_ramp
    ):
        """
        old_fte=27, ramp_fte=9, base_fte=18, new_fte=15 → reduction=12, 12≤18 → OK.
        """
        mock_ramp.return_value = (9, 3645.0)
        rec = make_realloc_input(
            month_overrides={"Jan-26": {"fte_avail": 15, "fte_avail_change": -12}}
        )
        result = self._run_preview(mock_months, mock_work_type, mock_config, mock_ramp, rec)
        assert result.success is True

    @patch("code.logics.forecast_reallocation_transformer.get_ramp_contribution_for_month")
    @patch("code.logics.forecast_reallocation_transformer.get_month_config_for_forecast")
    @patch("code.logics.forecast_reallocation_transformer._get_work_type_from_main_lob")
    @patch("code.logics.forecast_reallocation_transformer.get_months_dict")
    def test_ramp_active_reduction_exactly_base_boundary_succeeds(
        self, mock_months, mock_work_type, mock_config, mock_ramp
    ):
        """
        old_fte=27, ramp_fte=9, base_fte=18, new_fte=9 → reduction=18, 18≤18 → OK.
        Reducing exactly to the ramp floor is allowed.
        """
        mock_ramp.return_value = (9, 3645.0)
        rec = make_realloc_input(
            month_overrides={"Jan-26": {"fte_avail": 9, "fte_avail_change": -18}}
        )
        result = self._run_preview(mock_months, mock_work_type, mock_config, mock_ramp, rec)
        assert result.success is True

    @patch("code.logics.forecast_reallocation_transformer.get_ramp_contribution_for_month")
    @patch("code.logics.forecast_reallocation_transformer.get_month_config_for_forecast")
    @patch("code.logics.forecast_reallocation_transformer._get_work_type_from_main_lob")
    @patch("code.logics.forecast_reallocation_transformer.get_months_dict")
    def test_ramp_active_reduction_exceeds_base_raises_400(
        self, mock_months, mock_work_type, mock_config, mock_ramp
    ):
        """
        old_fte=27, ramp_fte=9, base_fte=18, new_fte=5 → reduction=22, 22>18 → 400.
        Cannot steal FTEs from the ramp headcount.
        """
        mock_ramp.return_value = (9, 3645.0)
        rec = make_realloc_input(
            month_overrides={"Jan-26": {"fte_avail": 5, "fte_avail_change": -22}}
        )
        with pytest.raises(HTTPException) as exc_info:
            self._run_preview(mock_months, mock_work_type, mock_config, mock_ramp, rec)

        assert exc_info.value.status_code == 400
        detail = exc_info.value.detail
        assert detail["success"] is False
        assert "Cannot reduce FTE_Avail" in detail["error"]
        assert "Jan-26" in detail["error"]
        assert "22" in detail["error"]   # reduction amount
        assert "18" in detail["error"]   # available base FTEs
        assert "recommendation" in detail

    @patch("code.logics.forecast_reallocation_transformer.get_ramp_contribution_for_month")
    @patch("code.logics.forecast_reallocation_transformer.get_month_config_for_forecast")
    @patch("code.logics.forecast_reallocation_transformer._get_work_type_from_main_lob")
    @patch("code.logics.forecast_reallocation_transformer.get_months_dict")
    def test_ramp_active_new_fte_below_ramp_fte_raises_400(
        self, mock_months, mock_work_type, mock_config, mock_ramp
    ):
        """
        Equivalently: new_fte_avail < ramp_fte → 400.
        old_fte=27, ramp_fte=9, new_fte=8 → below ramp floor → 400.
        """
        mock_ramp.return_value = (9, 3645.0)
        rec = make_realloc_input(
            month_overrides={"Jan-26": {"fte_avail": 8, "fte_avail_change": -19}}
        )
        with pytest.raises(HTTPException) as exc_info:
            self._run_preview(mock_months, mock_work_type, mock_config, mock_ramp, rec)

        assert exc_info.value.status_code == 400
        # recommendation should mention minimum new_fte_avail = ramp_fte = 9
        assert "9" in str(exc_info.value.detail["recommendation"])

    @patch("code.logics.forecast_reallocation_transformer.get_ramp_contribution_for_month")
    @patch("code.logics.forecast_reallocation_transformer.get_month_config_for_forecast")
    @patch("code.logics.forecast_reallocation_transformer._get_work_type_from_main_lob")
    @patch("code.logics.forecast_reallocation_transformer.get_months_dict")
    def test_ramp_active_fte_increase_always_passes(
        self, mock_months, mock_work_type, mock_config, mock_ramp
    ):
        """Increasing FTE is never blocked even when a ramp is active."""
        mock_ramp.return_value = (9, 3645.0)
        rec = make_realloc_input(
            month_overrides={"Jan-26": {"fte_avail": 40, "fte_avail_change": 13}}
        )
        result = self._run_preview(mock_months, mock_work_type, mock_config, mock_ramp, rec)
        assert result.success is True


# ============================================================================
# 4. FTE Reallocation — capacity split (base formula + ramp_capacity)
# ============================================================================


class TestFTECapacitySplit:
    """
    Tests that capacity in calculate_reallocation_preview is calculated as
    calculate_capacity(fte_avail - ramp_fte, config, cph) + ramp_capacity
    rather than calculate_capacity(fte_avail, config, cph).
    """

    @staticmethod
    def _run_preview_and_get_month1_capacity(mock_months, mock_work_type, mock_config,
                                              mock_ramp, fte_avail=27):
        mock_months.return_value = MONTHS_DICT
        mock_work_type.return_value = "Domestic"
        mock_config.return_value = SIX_MONTH_CONFIG

        # Use a DB capacity far from the calculated value to ensure the change triggers inclusion
        db_rec = make_forecast_row(fte_avail=fte_avail, capacity=0)
        session = make_session_mock([db_rec])
        cu = make_core_utils_mock(session)

        rec = make_realloc_input()  # no FTE changes, all months stay at 27
        from code.logics.forecast_reallocation_transformer import calculate_reallocation_preview
        result = calculate_reallocation_preview("January", 2026, [rec], cu)

        # The month1 capacity from the preview response
        assert len(result.modified_records) > 0
        return result.modified_records[0].months["Jan-26"].capacity

    @patch("code.logics.forecast_reallocation_transformer.get_ramp_contribution_for_month")
    @patch("code.logics.forecast_reallocation_transformer.get_month_config_for_forecast")
    @patch("code.logics.forecast_reallocation_transformer._get_work_type_from_main_lob")
    @patch("code.logics.forecast_reallocation_transformer.get_months_dict")
    def test_no_ramp_capacity_equals_full_formula(
        self, mock_months, mock_work_type, mock_config, mock_ramp
    ):
        """
        When ramp_fte=0, ramp_capacity=0:
        new_capacity = int(calculate_capacity(27, STD_CONFIG, 10)) = 45927.
        """
        mock_ramp.return_value = (0, 0.0)
        cap = self._run_preview_and_get_month1_capacity(
            mock_months, mock_work_type, mock_config, mock_ramp
        )
        assert cap == expected_capacity(27)

    @patch("code.logics.forecast_reallocation_transformer.get_ramp_contribution_for_month")
    @patch("code.logics.forecast_reallocation_transformer.get_month_config_for_forecast")
    @patch("code.logics.forecast_reallocation_transformer._get_work_type_from_main_lob")
    @patch("code.logics.forecast_reallocation_transformer.get_months_dict")
    def test_ramp_active_capacity_uses_base_fte_plus_ramp_cap(
        self, mock_months, mock_work_type, mock_config, mock_ramp
    ):
        """
        When ramp_fte=9, ramp_capacity=3645.0, fte_avail=27:
        base_fte = 27 - 9 = 18
        new_capacity = int(calculate_capacity(18, STD_CONFIG, 10) + 3645.0)
                     = int(30618.0 + 3645.0) = 34263.
        """
        ramp_cap = 9 * (100 / 100) * 10.0 * 9.0 * (1 - 0.10) * 5  # 3645.0
        mock_ramp.return_value = (9, ramp_cap)
        cap = self._run_preview_and_get_month1_capacity(
            mock_months, mock_work_type, mock_config, mock_ramp
        )
        expected_base_cap = expected_capacity(18)            # 18 base FTEs
        expected_total = int(expected_base_cap + ramp_cap)  # + ramp contribution
        assert cap == expected_total

    @patch("code.logics.forecast_reallocation_transformer.get_ramp_contribution_for_month")
    @patch("code.logics.forecast_reallocation_transformer.get_month_config_for_forecast")
    @patch("code.logics.forecast_reallocation_transformer._get_work_type_from_main_lob")
    @patch("code.logics.forecast_reallocation_transformer.get_months_dict")
    def test_ramp_split_differs_from_naive_formula(
        self, mock_months, mock_work_type, mock_config, mock_ramp
    ):
        """
        Verify that the ramp-split capacity is different from calculate_capacity(27, ...).
        This confirms the split actually changes the output (not an identity).
        ramp_fte=9, ramp_capacity=3645 → split result 34263 ≠ naive 45927.
        """
        ramp_cap = 9 * 1.0 * 10.0 * 9.0 * 0.90 * 5  # 3645.0
        mock_ramp.return_value = (9, ramp_cap)
        cap_with_ramp = self._run_preview_and_get_month1_capacity(
            mock_months, mock_work_type, mock_config, mock_ramp
        )
        # The naive (non-split) result
        cap_naive = expected_capacity(27)   # 45927
        assert cap_with_ramp != cap_naive
        # Ramp-split result must be less than naive (base has fewer FTEs, ramp adds less)
        assert cap_with_ramp < cap_naive


# ============================================================================
# 5. CPH preview — ramp-aware capacity split
# ============================================================================


class TestCPHPreviewRampCapacity:
    """
    Tests for calculate_cph_preview: capacity is split into
    calculate_capacity(fte_avail - ramp_fte, config, new_cph) + new_ramp_capacity.
    """

    def _run_cph_preview(self, mock_months, mock_config, ramp_return_value, fte_avail=27):
        mock_months.return_value = MONTHS_DICT
        mock_config.return_value = SIX_MONTH_CONFIG

        db_rec = make_forecast_row(fte_avail=fte_avail, capacity=1000)
        session = make_session_mock([db_rec])
        cu = make_core_utils_mock(session)

        # CPH change: 10 → 12
        modified_cph_records = [{
            "id": "cph_1",
            "lob": "Amisys",
            "case_type": "Claims",
            "target_cph": 10.0,
            "modified_target_cph": 12.0,
        }]

        from code.logics.cph_update_transformer import calculate_cph_preview
        with patch("code.logics.ramp_calculator.get_ramp_contribution_for_month",
                   return_value=ramp_return_value):
            with patch("code.logics.cph_update_transformer._get_work_type_from_main_lob",
                       return_value="Domestic"):
                with patch("code.logics.cph_update_transformer.get_months_dict",
                           return_value=MONTHS_DICT):
                    with patch("code.logics.cph_update_transformer.get_month_config_for_forecast",
                               return_value=SIX_MONTH_CONFIG):
                        return calculate_cph_preview("January", 2026, modified_cph_records, cu)

    def test_no_ramp_capacity_uses_full_fte_avail(self):
        """
        No ramp: capacity = calculate_capacity(fte_avail, config, new_cph).
        With fte_avail=27, new_cph=12: 27 × 21 × 9 × 0.90 × 12 = floor(55112.4) = 55112.
        """
        result = self._run_cph_preview(
            MagicMock(return_value=MONTHS_DICT),
            MagicMock(return_value=SIX_MONTH_CONFIG),
            ramp_return_value=(0, 0.0),
        )
        assert result.success is True
        cap = result.modified_records[0].months["Jan-26"].capacity
        assert cap == expected_capacity(27, cph=12.0)

    def test_ramp_active_capacity_uses_base_fte_and_new_ramp_capacity(self):
        """
        ramp_fte=9, new_ramp_capacity=4374, fte_avail=27, new_cph=12:
        base_fte = 18
        new_capacity = int(calculate_capacity(18, config, 12) + 4374)
                     = int(36741.6 → floor=36741 + 4374) = 41115.
        """
        # ramp_capacity at new_cph=12: 9 × 1.0 × 12 × 9 × 0.90 × 5 = 4374
        new_ramp_cap = 9 * 1.0 * 12.0 * 9.0 * (1 - 0.10) * 5
        result = self._run_cph_preview(
            MagicMock(return_value=MONTHS_DICT),
            MagicMock(return_value=SIX_MONTH_CONFIG),
            ramp_return_value=(9, new_ramp_cap),
        )
        assert result.success is True
        cap = result.modified_records[0].months["Jan-26"].capacity
        expected_base = expected_capacity(18, cph=12.0)
        expected_total = int(expected_base + new_ramp_cap)
        assert cap == expected_total

    def test_ramp_active_result_differs_from_naive_formula(self):
        """
        Sanity check: split result ≠ calculate_capacity(27, config, 12).
        """
        new_ramp_cap = 9 * 1.0 * 12.0 * 9.0 * 0.90 * 5
        result = self._run_cph_preview(
            MagicMock(return_value=MONTHS_DICT),
            MagicMock(return_value=SIX_MONTH_CONFIG),
            ramp_return_value=(9, new_ramp_cap),
        )
        cap_split = result.modified_records[0].months["Jan-26"].capacity
        cap_naive = expected_capacity(27, cph=12.0)
        assert cap_split != cap_naive


# ============================================================================
# 6. CPH apply — ramp-aware capacity split (update_forecast_from_cph_changes)
# ============================================================================


class TestCPHApplyRampCapacity:
    """
    Tests for update_forecast_from_cph_changes: capacity stored in DB is split into
    calculate_capacity(base_fte, config, new_cph) + new_ramp_capacity.
    """

    def _run_cph_apply(self, ramp_return_value, fte_avail=27):
        """
        Run update_forecast_from_cph_changes with one CPH change (10 → 12),
        one forecast row (fte_avail uniform across all months).

        Returns the updated forecast row mock so callers can inspect
        the Capacity_MonthX attributes set via setattr.
        """
        db_rec = make_forecast_row(fte_avail=fte_avail, capacity=1000)
        # session.query(...).filter(...).all() returns the row,
        # session.commit() is a no-op on the mock.
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        session.query.return_value.filter.return_value.all.return_value = [db_rec]
        db = MagicMock()
        db.SessionLocal.return_value = session
        cu = MagicMock()
        cu.get_db_manager.return_value = db

        modified_cph_records = [{
            "lob": "Amisys",
            "case_type": "Claims",
            "target_cph": 10.0,
            "modified_target_cph": 12.0,
        }]

        from code.logics.cph_update_transformer import update_forecast_from_cph_changes
        with patch("code.logics.ramp_calculator.get_ramp_contribution_for_month",
                   return_value=ramp_return_value):
            with patch("code.logics.cph_update_transformer._get_work_type_from_main_lob",
                       return_value="Domestic"):
                with patch("code.logics.cph_update_transformer.get_months_dict",
                           return_value=MONTHS_DICT):
                    with patch("code.logics.cph_update_transformer.get_month_config_for_forecast",
                               return_value=SIX_MONTH_CONFIG):
                        cph_updated, rows_affected = update_forecast_from_cph_changes(
                            "January", 2026, modified_cph_records, cu
                        )
        return cph_updated, rows_affected, db_rec

    def test_no_ramp_capacity_uses_full_fte_avail(self):
        """
        No ramp: Capacity_Month1 = calculate_capacity(27, config, 12) = 55112.
        """
        _, _, db_rec = self._run_cph_apply(ramp_return_value=(0, 0.0))
        cap = db_rec.Capacity_Month1
        assert cap == expected_capacity(27, cph=12.0)

    def test_ramp_active_capacity_stored_uses_base_fte(self):
        """
        Ramp active (ramp_fte=9, ramp_cap=4374, fte_avail=27, new_cph=12):
        Capacity_Month1 = int(calculate_capacity(18, config, 12) + 4374).
        """
        new_ramp_cap = 9 * 1.0 * 12.0 * 9.0 * 0.90 * 5  # 4374.0
        _, _, db_rec = self._run_cph_apply(ramp_return_value=(9, new_ramp_cap))
        cap = db_rec.Capacity_Month1
        expected_base = expected_capacity(18, cph=12.0)
        expected_total = int(expected_base + new_ramp_cap)
        # Note: update_forecast_from_cph_changes stores float (no int()) so allow small delta
        assert abs(cap - expected_total) < 1.0

    def test_cph_records_updated_count(self):
        """update_forecast_from_cph_changes returns (1, 1) for one CPH change affecting one row."""
        cph_updated, rows_affected, _ = self._run_cph_apply(ramp_return_value=(0, 0.0))
        assert cph_updated == 1
        assert rows_affected == 1

    def test_no_actual_change_returns_zeros(self):
        """When target_cph == modified_target_cph, no update is performed."""
        from code.logics.cph_update_transformer import update_forecast_from_cph_changes
        cu = MagicMock()
        no_change_records = [{"lob": "X", "case_type": "Y", "target_cph": 10.0, "modified_target_cph": 10.0}]
        with patch("code.logics.cph_update_transformer.get_months_dict", return_value=MONTHS_DICT):
            cph_updated, rows_affected = update_forecast_from_cph_changes(
                "January", 2026, no_change_records, cu
            )
        assert cph_updated == 0
        assert rows_affected == 0


# ============================================================================
# MAIN — run directly
# ============================================================================

if __name__ == "__main__":
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd="/Users/aswanthvishnu/Projects/manager_view_fastapi"
    )
    sys.exit(result.returncode)
