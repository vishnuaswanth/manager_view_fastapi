"""
Unit tests for PreProcessing.extract_forecast_demand() and get_month_year().

Covers:
  - extract_forecast_demand: concatenates pre-processed DataFrames from process_forecast_file
  - extract_forecast_demand: FTE Required / FTE Avail / Capacity columns preserved
  - extract_forecast_demand: correct 29-column structure in output DataFrame
  - extract_forecast_demand: empty dfs produces empty DataFrame
  - get_month_year: various filename patterns recognised and rejected

Architecture note:
  extract_forecast_demand now receives dfs where each value is a pd.DataFrame
  with MAPPING['forecast'] columns — already produced by sheet handlers.
  It simply concatenates them. Handler logic is tested separately.
"""

import pytest
import pandas as pd

from code.logics.core_utils import PreProcessing


# ─── Shared constants ─────────────────────────────────────────────────────────

MONTH_CODES = {
    "Month1": "April",
    "Month2": "May",
    "Month3": "June",
    "Month4": "July",
    "Month5": "August",
    "Month6": "September",
}

FTE_COLS = [f"FTE_Required_Month{i}" for i in range(1, 7)]
AVAIL_COLS = [f"FTE_Avail_Month{i}" for i in range(1, 7)]
CAPACITY_COLS = [f"Capacity_Month{i}" for i in range(1, 7)]
FORECAST_COLS = [f"Client_Forecast_Month{i}" for i in range(1, 7)]

META_COLS = [
    "Centene_Capacity_Plan_Main_LOB",
    "Centene_Capacity_Plan_State",
    "Centene_Capacity_Plan_Case_Type",
    "Centene_Capacity_Plan_Call_Type_ID",
    "Centene_Capacity_Plan_Target_CPH",
]

ALL_EXPECTED_COLS = META_COLS + FORECAST_COLS + FTE_COLS + AVAIL_COLS + CAPACITY_COLS  # 29


# ─── Helper: build a minimal ForecastModel DataFrame (handler output format) ──

def _make_forecast_df(
    lob: str = "Amisys Medicaid DOMESTIC",
    state: str = "TX",
    work_type: str = "FTC",
    forecast_val: int = 100,
    target_cph: float = 0.0,
    n_months: int = 6,
):
    """Build a single-row DataFrame with all 29 ForecastModel columns."""
    pre = PreProcessing("forecast")
    cols = pre.MAPPING["forecast"]
    row = {
        "Centene_Capacity_Plan_Main_LOB": lob,
        "Centene_Capacity_Plan_State": state,
        "Centene_Capacity_Plan_Case_Type": work_type,
        "Centene_Capacity_Plan_Call_Type_ID": f"{lob} {work_type.lower()}",
        "Centene_Capacity_Plan_Target_CPH": target_cph,
    }
    for i in range(1, 7):
        row[f"Client_Forecast_Month{i}"] = forecast_val if i <= n_months else 0
        row[f"FTE_Required_Month{i}"] = 0
        row[f"FTE_Avail_Month{i}"] = 0
        row[f"Capacity_Month{i}"] = 0
    return pd.DataFrame([row], columns=cols)


def _full_dfs():
    """Build dfs dict as returned by process_forecast_file (new format)."""
    return {
        "summary":            _make_forecast_df("Amisys Medicare",          state="N/A", forecast_val=200),
        "amisys_medicaid":    _make_forecast_df("Amisys Medicaid DOMESTIC", state="TX",  forecast_val=100),
        "amisys_mmp":         _make_forecast_df("Amisys MMP Domestic",      state="MI",  forecast_val=50),
        "amisys_aligned_dual":_make_forecast_df("AMISYS Aligned Dual Medicare Global", state="SC", forecast_val=30),
    }


def _pre():
    return PreProcessing("forecast")


# ─── Tests: extract_forecast_demand — column structure ────────────────────────

class TestExtractForecastDemandColumns:

    def test_output_has_all_29_columns(self):
        pre = _pre()
        df = pre.extract_forecast_demand(_full_dfs())
        assert not df.empty, "DataFrame should not be empty"
        assert len(df.columns) == 29, f"Expected 29 columns, got {len(df.columns)}: {df.columns.tolist()}"

    def test_all_expected_columns_present(self):
        pre = _pre()
        df = pre.extract_forecast_demand(_full_dfs())
        for col in ALL_EXPECTED_COLS:
            assert col in df.columns, f"Missing expected column: {col}"

    def test_meta_columns_are_strings(self):
        pre = _pre()
        df = pre.extract_forecast_demand(_full_dfs())
        for col in ["Centene_Capacity_Plan_Main_LOB", "Centene_Capacity_Plan_State",
                    "Centene_Capacity_Plan_Case_Type"]:
            assert pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]), \
                f"Column {col} should be string/object dtype, got {df[col].dtype}"


# ─── Tests: extract_forecast_demand — FTE / Capacity zeroing ─────────────────

class TestExtractForecastDemandZeroing:
    """FTE Required, FTE Avail, and Capacity must all be 0 on upload."""

    def _get_df(self):
        return _pre().extract_forecast_demand(_full_dfs())

    def test_fte_required_all_zero(self):
        df = self._get_df()
        for col in FTE_COLS:
            assert (df[col] == 0).all(), f"{col} must be 0 on upload, got non-zero values"

    def test_fte_avail_all_zero(self):
        df = self._get_df()
        for col in AVAIL_COLS:
            assert (df[col] == 0).all(), f"{col} must be 0 on upload, got non-zero values"

    def test_capacity_all_zero(self):
        df = self._get_df()
        for col in CAPACITY_COLS:
            assert (df[col] == 0).all(), f"{col} must be 0 on upload, got non-zero values"

    def test_client_forecast_not_all_zero(self):
        """Client Forecast should carry real values, not zeros."""
        df = self._get_df()
        any_nonzero = any((df[col] != 0).any() for col in FORECAST_COLS)
        assert any_nonzero, "At least some Client Forecast values should be non-zero"

    def test_only_forecast_has_values_rest_are_zero(self):
        """Exact boundary check: client forecast ≥ 0, all others == 0."""
        df = self._get_df()
        for col in FORECAST_COLS:
            assert (df[col] >= 0).all(), f"{col} should be non-negative"
        for col in FTE_COLS + AVAIL_COLS + CAPACITY_COLS:
            assert (df[col] == 0).all(), f"{col} should be exactly 0 on upload"


# ─── Tests: extract_forecast_demand — concatenation behaviour ─────────────────

class TestExtractForecastDemandValues:

    def test_rows_from_each_sheet_type_preserved(self):
        """Rows from each dfs_key survive the concat."""
        pre = _pre()
        df = pre.extract_forecast_demand(_full_dfs())
        lobs = set(df["Centene_Capacity_Plan_Main_LOB"].tolist())
        assert "Amisys Medicare" in lobs
        assert "Amisys Medicaid DOMESTIC" in lobs
        assert "Amisys MMP Domestic" in lobs

    def test_forecast_values_preserved(self):
        """Values in Client_Forecast columns are passed through unchanged."""
        dfs = {"amisys_medicaid": _make_forecast_df(forecast_val=123)}
        df = _pre().extract_forecast_demand(dfs)
        assert df["Client_Forecast_Month1"].iloc[0] == 123

    def test_target_cph_preserved(self):
        """Target CPH set in the handler DataFrame survives concat."""
        dfs = {"summary": _make_forecast_df(target_cph=45.0)}
        df = _pre().extract_forecast_demand(dfs)
        assert df["Centene_Capacity_Plan_Target_CPH"].iloc[0] == 45.0

    def test_empty_dfs_returns_empty_dataframe(self):
        """Empty dfs → empty DataFrame with correct columns."""
        df = _pre().extract_forecast_demand({})
        assert df.empty
        assert set(ALL_EXPECTED_COLS).issubset(set(df.columns))

    def test_dfs_with_empty_dataframes_returns_empty(self):
        """Dfs containing only empty DataFrames → empty result."""
        pre = _pre()
        empty_df = pd.DataFrame(columns=pre.MAPPING["forecast"])
        dfs = {"amisys_medicaid": empty_df, "amisys_mmp": empty_df}
        df = pre.extract_forecast_demand(dfs)
        assert df.empty

    def test_multiple_sheets_aggregate_rows(self):
        """Rows from multiple sheets are all included in output."""
        dfs = {
            "amisys_medicaid": _make_forecast_df("Amisys Medicaid DOMESTIC", forecast_val=100),
            "amisys_mmp":      _make_forecast_df("Amisys MMP Domestic",      forecast_val=50),
        }
        df = _pre().extract_forecast_demand(dfs)
        assert len(df) == 2
        lobs = set(df["Centene_Capacity_Plan_Main_LOB"].tolist())
        assert lobs == {"Amisys Medicaid DOMESTIC", "Amisys MMP Domestic"}

    def test_backward_compatible_with_month_codes_arg(self):
        """month_codes positional arg is accepted but ignored (backward compat)."""
        dfs = {"amisys_medicaid": _make_forecast_df()}
        df = _pre().extract_forecast_demand(dfs, MONTH_CODES)
        assert not df.empty

    def test_backward_compatible_with_target_cph_kwarg(self):
        """target_cph_lookup kwarg is accepted but ignored (backward compat)."""
        dfs = {"amisys_medicaid": _make_forecast_df()}
        df = _pre().extract_forecast_demand(dfs, MONTH_CODES, target_cph_lookup={})
        assert not df.empty


# ─── Tests: get_month_year — filename parsing ─────────────────────────────────

class TestGetMonthYear:

    def _parse(self, filename: str):
        return PreProcessing("forecast").get_month_year(filename)

    # Valid patterns

    def test_full_month_name_with_underscore(self):
        result = self._parse("forecast_January_2025.xlsx")
        assert result == {"Month": "January", "Year": "2025"}

    def test_full_month_name_with_hyphen(self):
        result = self._parse("forecast_January-2025.xlsx")
        assert result == {"Month": "January", "Year": "2025"}

    def test_abbreviated_month_with_underscore(self):
        result = self._parse("forecast_Jan_2025.xlsx")
        assert result == {"Month": "January", "Year": "2025"}

    def test_abbreviated_month_with_hyphen(self):
        result = self._parse("NTT_Forecast_Feb-2025.xlsx")
        assert result == {"Month": "February", "Year": "2025"}

    def test_abbreviated_month_mixed_case(self):
        result = self._parse("roster_MAR_2025.xlsx")
        assert result == {"Month": "March", "Year": "2025"}

    def test_full_month_mixed_case(self):
        result = self._parse("file_APRIL_2025.xlsx")
        assert result == {"Month": "April", "Year": "2025"}

    def test_december_recognized(self):
        result = self._parse("forecast_December_2024.xlsx")
        assert result == {"Month": "December", "Year": "2024"}

    def test_month_name_with_spaces_in_filename(self):
        result = self._parse("NTT Forecast - Capacity and HC - Feb 2025 V2.xlsx")
        assert result["Month"] == "February"
        assert result["Year"] == "2025"

    # Invalid patterns

    def test_no_month_returns_none(self):
        assert self._parse("roster_data_2025.xlsx") is None

    def test_no_year_returns_none(self):
        assert self._parse("forecast_January.xlsx") is None

    def test_empty_filename_returns_none(self):
        assert self._parse("") is None

    def test_random_string_returns_none(self):
        assert self._parse("abcdef.xlsx") is None
