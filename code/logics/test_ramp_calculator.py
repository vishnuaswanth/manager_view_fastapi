"""
Unit and integration tests for the ramp calculation feature.

Covers:
  - Pure logic: _parse_month_key_to_label, _compute_ramp_totals
  - Month resolution: _resolve_month_suffix
  - Router validation: _validate_ramp_request
  - DB-backed flows: get_applied_ramp, preview_ramp, apply_ramp

Run with:
    python3 -m pytest code/logics/test_ramp_calculator.py -v
"""

import pytest
from dataclasses import dataclass
from typing import List
from unittest.mock import MagicMock, patch, PropertyMock

from fastapi import HTTPException


# ============================================================================
# HELPERS / FIXTURES
# ============================================================================

@dataclass
class FakeWeek:
    """Minimal stand-in for RampWeek Pydantic model for pure-logic tests."""
    label: str
    startDate: str
    endDate: str
    workingDays: int
    rampPercent: float
    rampEmployees: int


def make_config(working_days=21, occupancy=0.95, shrinkage=0.10, work_hours=9.0):
    """Return a standard month config dict."""
    return {
        "working_days": working_days,
        "occupancy": occupancy,
        "shrinkage": shrinkage,
        "work_hours": work_hours
    }


# ============================================================================
# 1. _parse_month_key_to_label
# ============================================================================

class TestParseMonthKeyToLabel:
    """Tests for _parse_month_key_to_label — pure string conversion."""

    def _call(self, month_key: str) -> str:
        from code.logics.ramp_calculator import _parse_month_key_to_label
        return _parse_month_key_to_label(month_key)

    def test_january_2026(self):
        assert self._call("2026-01") == "Jan-26"

    def test_december_2025(self):
        assert self._call("2025-12") == "Dec-25"

    def test_june_2024(self):
        assert self._call("2024-06") == "Jun-24"

    def test_march_2026(self):
        assert self._call("2026-03") == "Mar-26"

    def test_october_2025(self):
        assert self._call("2025-10") == "Oct-25"

    def test_february_2030(self):
        assert self._call("2030-02") == "Feb-30"

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            self._call("bad-key")

    def test_partial_format_raises(self):
        """strptime('%Y-%m') does allow single-digit months, so test a genuinely invalid key."""
        with pytest.raises(ValueError):
            self._call("2026-13")  # month 13 doesn't exist — strptime raises


# ============================================================================
# 2. _compute_ramp_totals
# ============================================================================

class TestComputeRampTotals:
    """Tests for _compute_ramp_totals — pure arithmetic, no DB."""

    def _call(self, weeks, config, target_cph):
        from code.logics.ramp_calculator import _compute_ramp_totals
        return _compute_ramp_totals(weeks, config, target_cph)

    def test_single_week_basic(self):
        """
        Capacity = employees × CPH × work_hours × occupancy × (1-shrinkage) × working_days
                 = 10 × 5 × 9 × 0.95 × 0.9 × 5 = 10 * 5 * 9 * 0.855 * 5
        """
        weeks = [FakeWeek("W1", "2026-01-05", "2026-01-09", 5, 100.0, 10)]
        config = make_config(working_days=21, occupancy=0.95, shrinkage=0.10, work_hours=9.0)
        total_cap, max_emp = self._call(weeks, config, 5.0)
        # 10 * 5 * 9 * 0.95 * 0.90 * 5 = 10 * 5 * 9 * 0.855 * 5 = 1923.75
        expected = 10 * 5.0 * 9.0 * 0.95 * 0.90 * 5
        assert abs(total_cap - expected) < 0.001
        assert max_emp == 10

    def test_multiple_weeks_sum(self):
        """Total capacity is sum across all weeks."""
        weeks = [
            FakeWeek("W1", "2026-01-05", "2026-01-09", 5, 50.0, 5),
            FakeWeek("W2", "2026-01-12", "2026-01-16", 5, 75.0, 10),
            FakeWeek("W3", "2026-01-19", "2026-01-23", 5, 100.0, 15),
        ]
        config = make_config()
        target_cph = 10.0
        total_cap, max_emp = self._call(weeks, config, target_cph)

        # Compute expected manually
        def week_cap(emp, wd):
            return emp * target_cph * 9.0 * 0.95 * 0.90 * wd
        expected = week_cap(5, 5) + week_cap(10, 5) + week_cap(15, 5)
        assert abs(total_cap - expected) < 0.001
        assert max_emp == 15  # max over all weeks

    def test_max_employees_is_peak_not_sum(self):
        """max_ramp_employees = max, not sum."""
        weeks = [
            FakeWeek("W1", "2026-01-05", "2026-01-09", 5, 25.0, 3),
            FakeWeek("W2", "2026-01-12", "2026-01-16", 5, 75.0, 8),
            FakeWeek("W3", "2026-01-19", "2026-01-23", 5, 100.0, 20),
        ]
        _, max_emp = self._call(weeks, make_config(), 10.0)
        assert max_emp == 20

    def test_zero_employees_zero_capacity(self):
        """Weeks with 0 employees contribute 0 capacity."""
        weeks = [FakeWeek("W1", "2026-01-05", "2026-01-09", 5, 0.0, 0)]
        total_cap, max_emp = self._call(weeks, make_config(), 10.0)
        assert total_cap == 0.0
        assert max_emp == 0

    def test_zero_working_days_zero_capacity(self):
        """Weeks with 0 working days contribute 0 capacity."""
        weeks = [FakeWeek("W1", "2026-01-05", "2026-01-09", 0, 100.0, 10)]
        total_cap, _ = self._call(weeks, make_config(), 10.0)
        assert total_cap == 0.0

    def test_zero_target_cph_zero_capacity(self):
        """Target CPH of 0 yields 0 capacity."""
        weeks = [FakeWeek("W1", "2026-01-05", "2026-01-09", 5, 100.0, 10)]
        total_cap, _ = self._call(weeks, make_config(), 0.0)
        assert total_cap == 0.0

    def test_high_shrinkage_reduces_capacity(self):
        """Higher shrinkage should reduce output capacity."""
        weeks = [FakeWeek("W1", "2026-01-05", "2026-01-09", 5, 100.0, 10)]
        low_shrinkage_cap, _ = self._call(weeks, make_config(shrinkage=0.05), 10.0)
        high_shrinkage_cap, _ = self._call(weeks, make_config(shrinkage=0.30), 10.0)
        assert high_shrinkage_cap < low_shrinkage_cap

    def test_config_occupancy_scales_capacity(self):
        """Higher occupancy increases output capacity."""
        weeks = [FakeWeek("W1", "2026-01-05", "2026-01-09", 5, 100.0, 10)]
        low_occ_cap, _ = self._call(weeks, make_config(occupancy=0.80), 10.0)
        high_occ_cap, _ = self._call(weeks, make_config(occupancy=0.95), 10.0)
        assert high_occ_cap > low_occ_cap

    def test_mixed_zero_and_nonzero_weeks(self):
        """Max over weeks that include zero-employee weeks."""
        weeks = [
            FakeWeek("W1", "2026-01-05", "2026-01-09", 5, 0.0, 0),
            FakeWeek("W2", "2026-01-12", "2026-01-16", 5, 50.0, 7),
        ]
        _, max_emp = self._call(weeks, make_config(), 10.0)
        assert max_emp == 7


# ============================================================================
# 3. _resolve_month_suffix
# ============================================================================

class TestResolveMonthSuffix:
    """Tests for _resolve_month_suffix — uses mocked months_dict."""

    def _call(self, row, month_key):
        from code.logics.ramp_calculator import _resolve_month_suffix
        return _resolve_month_suffix(row, month_key)

    def _make_row(self, report_month="January", report_year=2026):
        row = MagicMock()
        row.Month = report_month
        row.Year = report_year
        return row

    @patch("code.logics.ramp_calculator.get_months_dict")
    def test_resolves_first_month(self, mock_months):
        mock_months.return_value = {
            "month1": "Feb-26",
            "month2": "Mar-26",
            "month3": "Apr-26",
            "month4": "May-26",
            "month5": "Jun-26",
            "month6": "Jul-26",
        }
        row = self._make_row("January", 2026)
        suffix, label = self._call(row, "2026-02")
        assert suffix == "1"
        assert label == "Feb-26"

    @patch("code.logics.ramp_calculator.get_months_dict")
    def test_resolves_last_month(self, mock_months):
        mock_months.return_value = {
            "month1": "Feb-26",
            "month2": "Mar-26",
            "month3": "Apr-26",
            "month4": "May-26",
            "month5": "Jun-26",
            "month6": "Jul-26",
        }
        row = self._make_row("January", 2026)
        suffix, label = self._call(row, "2026-07")
        assert suffix == "6"
        assert label == "Jul-26"

    @patch("code.logics.ramp_calculator.get_months_dict")
    def test_month_not_in_period_raises_400(self, mock_months):
        mock_months.return_value = {
            "month1": "Feb-26",
            "month2": "Mar-26",
            "month3": "Apr-26",
            "month4": "May-26",
            "month5": "Jun-26",
            "month6": "Jul-26",
        }
        row = self._make_row("January", 2026)
        with pytest.raises(HTTPException) as exc_info:
            self._call(row, "2026-01")  # Jan-26 not in period
        assert exc_info.value.status_code == 400
        assert "not in this report period" in str(exc_info.value.detail)

    @patch("code.logics.ramp_calculator.get_months_dict")
    def test_resolves_middle_month(self, mock_months):
        mock_months.return_value = {
            "month1": "Apr-25",
            "month2": "May-25",
            "month3": "Jun-25",
            "month4": "Jul-25",
            "month5": "Aug-25",
            "month6": "Sep-25",
        }
        row = self._make_row("March", 2025)
        suffix, label = self._call(row, "2025-06")
        assert suffix == "3"
        assert label == "Jun-25"


# ============================================================================
# 4. Router validation: _validate_ramp_request
# ============================================================================

class MockRampWeek:
    """Minimal mock for RampWeek as used by validator."""
    def __init__(self, ramp_employees):
        self.rampEmployees = ramp_employees


class MockPreviewRequest:
    def __init__(self, weeks, total_ramp_employees):
        self.weeks = [MockRampWeek(e) for e in weeks]
        self.totalRampEmployees = total_ramp_employees


class TestValidateRampRequest:
    """Tests for _validate_ramp_request — pure HTTP error checking."""

    def _call(self, weeks_employees: list, total: int):
        from code.api.routers.ramp_router import _validate_ramp_request
        req = MockPreviewRequest(weeks_employees, total)
        _validate_ramp_request(req)

    def test_valid_request_passes(self):
        """Valid request with matching total should not raise."""
        self._call([5, 10, 15], 30)

    def test_total_mismatch_raises_400(self):
        """Mismatched totalRampEmployees should raise 400."""
        with pytest.raises(HTTPException) as exc_info:
            self._call([5, 10], 20)  # sum=15, but total=20
        assert exc_info.value.status_code == 400
        assert "totalRampEmployees" in str(exc_info.value.detail)

    def test_all_zeros_raises_400(self):
        """All-zero rampEmployees should raise 400."""
        with pytest.raises(HTTPException) as exc_info:
            self._call([0, 0, 0], 0)
        assert exc_info.value.status_code == 400
        assert "zero" in str(exc_info.value.detail).lower()

    def test_single_nonzero_week_passes(self):
        """Single non-zero week is valid."""
        self._call([10], 10)

    def test_mixed_with_zeros_passes_if_total_matches(self):
        """Mix of zero and non-zero weeks is valid if total matches."""
        self._call([0, 5, 0], 5)

    def test_one_of_zeros_total_matches_but_all_zero(self):
        """If all employees are 0, should still fail even if total matches (0=0)."""
        with pytest.raises(HTTPException) as exc_info:
            self._call([0], 0)
        assert exc_info.value.status_code == 400


# ============================================================================
# 5. _get_ramp_month_config — fallback behavior
# ============================================================================

class TestGetRampMonthConfig:
    """Tests for _get_ramp_month_config — focus on fallback defaults."""

    @patch("code.logics.ramp_calculator.core_utils")
    def test_returns_defaults_when_no_config(self, mock_cu):
        """When no MonthConfigurationModel found, defaults are returned."""
        from code.logics.ramp_calculator import _get_ramp_month_config

        # Mock the DB session to return None for config query
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.first.return_value = None

        mock_db = MagicMock()
        mock_db.SessionLocal.return_value = mock_session
        mock_cu.get_db_manager.return_value = mock_db

        with patch("code.logics.cph_update_transformer._get_work_type_from_main_lob", return_value="Domestic"):
            config = _get_ramp_month_config("Jan-26", "Amisys Medicaid DOMESTIC", "Claims")

        assert "working_days" in config
        assert "occupancy" in config
        assert "shrinkage" in config
        assert "work_hours" in config
        assert config["working_days"] == 21
        assert config["occupancy"] == 0.95

    @patch("code.logics.ramp_calculator.core_utils")
    def test_returns_db_values_when_config_found(self, mock_cu):
        """When config is found in DB, those values are returned."""
        from code.logics.ramp_calculator import _get_ramp_month_config

        mock_config_row = MagicMock()
        mock_config_row.WorkingDays = 20
        mock_config_row.Occupancy = 0.88
        mock_config_row.Shrinkage = 0.12
        mock_config_row.WorkHours = 8.0

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.first.return_value = mock_config_row

        mock_db = MagicMock()
        mock_db.SessionLocal.return_value = mock_session
        mock_cu.get_db_manager.return_value = mock_db

        with patch("code.logics.cph_update_transformer._get_work_type_from_main_lob", return_value="Global"):
            config = _get_ramp_month_config("Jan-26", "Amisys Medicaid GLOBAL", "Claims")

        assert config["working_days"] == 20
        assert config["occupancy"] == 0.88
        assert config["shrinkage"] == 0.12
        assert config["work_hours"] == 8.0


# ============================================================================
# 6. get_applied_ramp — response structure
# ============================================================================

class TestGetAppliedRamp:
    """Tests for get_applied_ramp — DB mocked."""

    def _setup_ramp_db(self, mock_cu, ramp_rows):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        # forecast row mock
        mock_forecast = MagicMock()
        mock_session.get.return_value = mock_forecast

        # ramp query chain
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = ramp_rows

        mock_db = MagicMock()
        mock_db.SessionLocal.return_value = mock_session
        mock_cu.get_db_manager.return_value = mock_db

    @patch("code.logics.ramp_calculator.core_utils")
    def test_no_ramp_returns_false(self, mock_cu):
        """When no ramp rows exist, ramp_applied=False."""
        self._setup_ramp_db(mock_cu, [])

        from code.logics.ramp_calculator import get_applied_ramp
        result = get_applied_ramp(1, "2026-01")

        assert result["success"] is True
        assert result["ramp_applied"] is False
        assert result["ramp_data"] is None
        assert result["forecast_id"] == 1
        assert result["month_key"] == "2026-01"

    @patch("code.logics.ramp_calculator.core_utils")
    def test_with_ramp_rows_returns_true(self, mock_cu):
        """When ramp rows exist, ramp_applied=True with data list."""
        from datetime import datetime

        mock_row = MagicMock()
        mock_row.week_label = "Jan-1-2026"
        mock_row.start_date = "2026-01-05"
        mock_row.end_date = "2026-01-09"
        mock_row.working_days = 5
        mock_row.ramp_percent = 50.0
        mock_row.employee_count = 10
        mock_row.applied_at = datetime(2026, 1, 10)
        mock_row.applied_by = "system"

        self._setup_ramp_db(mock_cu, [mock_row])

        from code.logics.ramp_calculator import get_applied_ramp
        result = get_applied_ramp(1, "2026-01")

        assert result["success"] is True
        assert result["ramp_applied"] is True
        assert len(result["ramp_data"]) == 1
        week = result["ramp_data"][0]
        assert week["week_label"] == "Jan-1-2026"
        assert week["employee_count"] == 10

    @patch("code.logics.ramp_calculator.core_utils")
    def test_forecast_not_found_raises_404(self, mock_cu):
        """When forecast row doesn't exist, HTTPException 404 is raised."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = None  # Not found

        mock_db = MagicMock()
        mock_db.SessionLocal.return_value = mock_session
        mock_cu.get_db_manager.return_value = mock_db

        from code.logics.ramp_calculator import get_applied_ramp
        with pytest.raises(HTTPException) as exc_info:
            get_applied_ramp(9999, "2026-01")

        assert exc_info.value.status_code == 404


# ============================================================================
# 7. preview_ramp — calculations are correct
# ============================================================================

class TestPreviewRamp:
    """Tests for preview_ramp — verifies projected values are computed correctly."""

    def _make_weeks(self, employees, working_days=5):
        return [FakeWeek("W1", "2026-01-05", "2026-01-09", working_days, 100.0, employees)]

    @patch("code.logics.ramp_calculator._get_ramp_month_config")
    @patch("code.logics.ramp_calculator._resolve_month_suffix")
    @patch("code.logics.ramp_calculator.core_utils")
    def test_projected_values_correct(self, mock_cu, mock_resolve, mock_config):
        """preview_ramp should return correct current/projected/diff."""
        mock_resolve.return_value = ("1", "Jan-26")
        mock_config.return_value = make_config(working_days=5)

        # First DB call (fetch row + resolve)
        mock_row = MagicMock()
        mock_row.Centene_Capacity_Plan_Target_CPH = 10
        mock_row.Centene_Capacity_Plan_Main_LOB = "Amisys Medicaid DOMESTIC"
        mock_row.Centene_Capacity_Plan_Case_Type = "Claims"
        mock_row.FTE_Avail_Month1 = 20
        mock_row.Capacity_Month1 = 1000

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = mock_row

        mock_db = MagicMock()
        mock_db.SessionLocal.return_value = mock_session
        mock_cu.get_db_manager.return_value = mock_db

        weeks = self._make_weeks(employees=5, working_days=5)

        from code.logics.ramp_calculator import preview_ramp
        result = preview_ramp(1, "2026-01", weeks)

        assert result["success"] is True
        assert result["month_label"] == "Jan-26"
        # Current values from mock
        assert result["current"]["fte_avail"] == 20
        assert result["current"]["capacity"] == 1000
        # max_ramp_employees = 5
        assert result["projected"]["fte_avail"] == 25
        # diff fte_avail = max_ramp_employees = 5
        assert result["diff"]["fte_avail"] == 5
        # Capacity delta > 0
        assert result["diff"]["capacity"] > 0

    @patch("code.logics.ramp_calculator._get_ramp_month_config")
    @patch("code.logics.ramp_calculator._resolve_month_suffix")
    @patch("code.logics.ramp_calculator.core_utils")
    def test_zero_employee_weeks_no_change(self, mock_cu, mock_resolve, mock_config):
        """Weeks with 0 employees should give 0 diff."""
        mock_resolve.return_value = ("2", "Feb-26")
        mock_config.return_value = make_config()

        mock_row = MagicMock()
        mock_row.Centene_Capacity_Plan_Target_CPH = 10
        mock_row.Centene_Capacity_Plan_Main_LOB = "Amisys Medicaid DOMESTIC"
        mock_row.Centene_Capacity_Plan_Case_Type = "Claims"
        mock_row.FTE_Avail_Month2 = 30
        mock_row.Capacity_Month2 = 2000

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = mock_row

        mock_db = MagicMock()
        mock_db.SessionLocal.return_value = mock_session
        mock_cu.get_db_manager.return_value = mock_db

        weeks = [FakeWeek("W1", "2026-02-02", "2026-02-06", 5, 0.0, 0)]

        from code.logics.ramp_calculator import preview_ramp
        result = preview_ramp(1, "2026-02", weeks)

        assert result["diff"]["fte_avail"] == 0
        assert result["diff"]["capacity"] == 0.0


# ============================================================================
# 8. Ramp router — Pydantic model validation via test client
# ============================================================================

class TestRampRouterPydantic:
    """Tests for Pydantic validation on ramp router request models."""

    def test_ramp_week_valid(self):
        from code.api.routers.ramp_router import RampWeek
        week = RampWeek(
            label="Jan-1-2026",
            startDate="2026-01-05",
            endDate="2026-01-09",
            workingDays=5,
            rampPercent=50.0,
            rampEmployees=10
        )
        assert week.rampEmployees == 10

    def test_ramp_week_negative_employees_rejected(self):
        from code.api.routers.ramp_router import RampWeek
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RampWeek(
                label="W1",
                startDate="2026-01-05",
                endDate="2026-01-09",
                workingDays=5,
                rampPercent=50.0,
                rampEmployees=-1  # < 0
            )

    def test_ramp_week_ramp_percent_over_100_rejected(self):
        from code.api.routers.ramp_router import RampWeek
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RampWeek(
                label="W1",
                startDate="2026-01-05",
                endDate="2026-01-09",
                workingDays=5,
                rampPercent=150.0,  # > 100
                rampEmployees=5
            )

    def test_ramp_week_negative_ramp_percent_rejected(self):
        from code.api.routers.ramp_router import RampWeek
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RampWeek(
                label="W1",
                startDate="2026-01-05",
                endDate="2026-01-09",
                workingDays=5,
                rampPercent=-10.0,  # < 0
                rampEmployees=5
            )

    def test_ramp_week_negative_working_days_rejected(self):
        from code.api.routers.ramp_router import RampWeek
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RampWeek(
                label="W1",
                startDate="2026-01-05",
                endDate="2026-01-09",
                workingDays=-1,  # < 0
                rampPercent=50.0,
                rampEmployees=5
            )

    def test_ramp_week_extra_fields_rejected(self):
        """extra='forbid' should reject unknown fields."""
        from code.api.routers.ramp_router import RampWeek
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RampWeek(
                label="W1",
                startDate="2026-01-05",
                endDate="2026-01-09",
                workingDays=5,
                rampPercent=50.0,
                rampEmployees=5,
                unknownField="bad"
            )

    def test_preview_request_valid(self):
        from code.api.routers.ramp_router import RampPreviewRequest, RampWeek
        req = RampPreviewRequest(
            weeks=[
                RampWeek(label="W1", startDate="2026-01-05", endDate="2026-01-09",
                         workingDays=5, rampPercent=50.0, rampEmployees=10)
            ],
            totalRampEmployees=10
        )
        assert len(req.weeks) == 1

    def test_apply_request_with_notes(self):
        from code.api.routers.ramp_router import RampApplyRequest, RampWeek
        req = RampApplyRequest(
            weeks=[
                RampWeek(label="W1", startDate="2026-01-05", endDate="2026-01-09",
                         workingDays=5, rampPercent=50.0, rampEmployees=10)
            ],
            totalRampEmployees=10,
            user_notes="Test ramp application"
        )
        assert req.user_notes == "Test ramp application"

    def test_apply_request_notes_too_long_rejected(self):
        from code.api.routers.ramp_router import RampApplyRequest, RampWeek
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RampApplyRequest(
                weeks=[
                    RampWeek(label="W1", startDate="2026-01-05", endDate="2026-01-09",
                             workingDays=5, rampPercent=50.0, rampEmployees=10)
                ],
                totalRampEmployees=10,
                user_notes="x" * 1001  # > 1000 chars
            )


# ============================================================================
# 9. change_types — CHANGE_TYPE_RAMP_CALCULATION
# ============================================================================

class TestChangeTypes:
    """Tests for ramp change type constant registration."""

    def test_ramp_constant_exists(self):
        from code.logics.config.change_types import CHANGE_TYPE_RAMP_CALCULATION
        assert CHANGE_TYPE_RAMP_CALCULATION == "Ramp Calculation"

    def test_ramp_constant_in_change_types_list(self):
        from code.logics.config.change_types import CHANGE_TYPES, CHANGE_TYPE_RAMP_CALCULATION
        assert CHANGE_TYPE_RAMP_CALCULATION in CHANGE_TYPES

    def test_validate_change_type_accepts_ramp(self):
        from code.logics.config.change_types import validate_change_type
        assert validate_change_type("Ramp Calculation") is True

    def test_validate_change_type_rejects_unknown(self):
        from code.logics.config.change_types import validate_change_type
        assert validate_change_type("Unknown Change") is False


# ============================================================================
# 10. RampModel — DB model structure
# ============================================================================

class TestRampModelStructure:
    """Tests for RampModel — verifies field presence and defaults."""

    def test_ramp_model_importable(self):
        from code.logics.db import RampModel
        assert RampModel is not None

    def test_ramp_model_has_required_fields(self):
        from code.logics.db import RampModel
        model_fields = RampModel.model_fields
        required = [
            "forecast_id", "month_key", "week_label",
            "start_date", "end_date", "working_days",
            "ramp_percent", "employee_count"
        ]
        for field in required:
            assert field in model_fields, f"Missing field: {field}"

    def test_ramp_model_defaults(self):
        """applied_by defaults to 'system'."""
        from code.logics.db import RampModel
        # Check default value is set for applied_by
        field_info = RampModel.model_fields.get("applied_by")
        assert field_info is not None
        assert field_info.default == "system"


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
