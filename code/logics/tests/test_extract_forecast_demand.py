"""
Unit tests for PreProcessing.extract_forecast_demand() and get_month_year().

Covers:
  - extract_forecast_demand: FTE Required / FTE Avail / Capacity always 0 on upload
  - extract_forecast_demand: Client Forecast populated from each sheet type
  - extract_forecast_demand: correct 29-column structure in output DataFrame
  - extract_forecast_demand: empty dfs produces empty DataFrame
  - get_month_year: various filename patterns recognised and rejected
"""

import io
import pytest
import pandas as pd
from unittest.mock import patch

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


# ─── Helpers to build minimal dfs dicts ───────────────────────────────────────

def _make_nonmmp_df():
    """Minimal NonMMP DataFrame with State, Month, and one work-type forecast column.

    The extractor (_extract_nonmmp_demand) discovers work types from columns where
    col[0] contains 'Forecast - Volume', and _build_forecast_row reads values from
    columns where col[0] contains 'WFM TO PROVIDE' and work_type is in the tuple.
    We satisfy both by using 'WFM TO PROVIDE' at col[0] (which also contains
    'Forecast - Volume' via a combined label) — or by keeping one column that
    satisfies work-type discovery and another that satisfies value extraction.

    Simplest approach: col[0] = 'Forecast - Volume WFM TO PROVIDE' satisfies both.
    """
    cols = pd.MultiIndex.from_tuples([
        ('', '', 'State'),
        ('', '', 'Month'),
        # col[0] must contain 'Forecast - Volume' (for work_type discovery)
        # AND col[0] must contain 'WFM TO PROVIDE' (for value extraction in _build_forecast_row)
        ('Forecast - Volume WFM TO PROVIDE', 'WFM TO PROVIDE', 'FTC'),
    ])
    rows = []
    for month in MONTH_CODES.values():
        rows.append(['TX', month, 100])
    return pd.DataFrame(rows, columns=cols)


def _make_mmp_df():
    """Minimal MMP DataFrame with State, Month, boundary markers, and one work-type column.

    _extract_mmp_demand calls get_columns_between_column_names(df, 0, 'Mo St', 'Year')
    to discover work types. The 'Mo St' and 'Year' boundary columns must be present at
    level 0. State and Month columns are placed before 'Mo St' so they are not mistaken
    for work types.
    """
    cols = pd.MultiIndex.from_tuples([
        ('State', 'State'),        # state column — before Mo St boundary
        ('Month', 'Month'),        # month column — before Mo St boundary
        ('Mo St', 'Mo St'),        # start boundary for work-type range
        ('FTC-MMP', 'FTC-MMP'),   # actual work type
        ('Year', 'Year'),           # end boundary for work-type range
    ])
    rows = []
    for month in MONTH_CODES.values():
        rows.append(['MI', month, None, 50, None])
    return pd.DataFrame(rows, columns=cols)


def _make_summary_df(lob_name: str = "Amisys Medicare"):
    """Minimal Summary DataFrame for one LOB."""
    cols = pd.MultiIndex.from_tuples(
        [(lob_name, lob_name, 'Work Type', 'Work Type'),
         (lob_name, lob_name, 'CPH', 'CPH')]
        + [(lob_name, lob_name, m, m) for m in MONTH_CODES.values()]
    )
    data = [['FTC', 45] + [200] * 6]
    return pd.DataFrame(data, columns=cols)


def _make_aligned_dual_df():
    """Minimal Aligned Dual DataFrame."""
    rows = []
    for month in MONTH_CODES.values():
        rows.append({'State': 'SC', 'Month': month, 'Area': 'Global', 'FTC-Medicare Aligned Duals': 30})
    return pd.DataFrame(rows)


def _full_dfs():
    """Build the complete nested dfs dict as returned by process_forecast_file()."""
    nonmmp_domestic = _make_nonmmp_df()
    nonmmp_global = _make_nonmmp_df()
    nonmmp_global[('', '', 'State')] = 'IL'

    mmp_df = _make_mmp_df()
    domestic_mask = mmp_df[('State', 'State')].isin(['MI'])
    global_mask = mmp_df[('State', 'State')].isin(['SC'])

    return {
        "medicare_medicaid_nonmmp": {
            "Amisys Medicaid DOMESTIC": nonmmp_domestic,
            "Amisys Medicaid GLOBAL": nonmmp_global,
        },
        "medicare_medicaid_mmp": {
            "AMISYS MMP Domestic": mmp_df[domestic_mask].reset_index(drop=True),
            "AMISYS MMP Global": mmp_df[global_mask].reset_index(drop=True),
        },
        "medicare_medicaid_summary": {
            "Amisys Medicare Non-MMP Global": _make_summary_df("Amisys Medicare"),
        },
        "medicare_medicaid_aligned_dual": {
            "AMISYS Aligned Dual Medicare Global": _make_aligned_dual_df(),
        },
    }


def _pre():
    return PreProcessing("forecast")


# ─── Tests: extract_forecast_demand — column structure ────────────────────────

class TestExtractForecastDemandColumns:

    def test_output_has_all_29_columns(self):
        pre = _pre()
        with patch('code.logics.target_cph_utils.get_all_target_cph_as_dict', return_value={}):
            df = pre.extract_forecast_demand(_full_dfs(), MONTH_CODES)

        assert not df.empty, "DataFrame should not be empty"
        assert len(df.columns) == 29, f"Expected 29 columns, got {len(df.columns)}: {df.columns.tolist()}"

    def test_all_expected_columns_present(self):
        pre = _pre()
        with patch('code.logics.target_cph_utils.get_all_target_cph_as_dict', return_value={}):
            df = pre.extract_forecast_demand(_full_dfs(), MONTH_CODES)

        for col in ALL_EXPECTED_COLS:
            assert col in df.columns, f"Missing expected column: {col}"

    def test_meta_columns_are_strings(self):
        pre = _pre()
        with patch('code.logics.target_cph_utils.get_all_target_cph_as_dict', return_value={}):
            df = pre.extract_forecast_demand(_full_dfs(), MONTH_CODES)

        for col in ["Centene_Capacity_Plan_Main_LOB", "Centene_Capacity_Plan_State",
                    "Centene_Capacity_Plan_Case_Type"]:
            assert pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]), \
                f"Column {col} should be string/object dtype, got {df[col].dtype}"


# ─── Tests: extract_forecast_demand — FTE / Capacity zeroing ─────────────────

class TestExtractForecastDemandZeroing:
    """Critical: FTE Required, FTE Avail, and Capacity must ALL be 0 on upload."""

    def _get_df(self):
        pre = _pre()
        with patch('code.logics.target_cph_utils.get_all_target_cph_as_dict', return_value={}):
            return pre.extract_forecast_demand(_full_dfs(), MONTH_CODES)

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


# ─── Tests: extract_forecast_demand — Client Forecast values per sheet type ───

class TestExtractForecastDemandValues:

    def test_nonmmp_forecast_values_extracted(self):
        """NonMMP sheet provides forecast values per state/work-type/month."""
        dfs = {
            "medicare_medicaid_nonmmp": {
                "Amisys Medicaid DOMESTIC": _make_nonmmp_df(),
            },
            "medicare_medicaid_mmp": {},
            "medicare_medicaid_summary": {},
            "medicare_medicaid_aligned_dual": {},
        }
        pre = _pre()
        with patch('code.logics.target_cph_utils.get_all_target_cph_as_dict', return_value={}):
            df = pre.extract_forecast_demand(dfs, MONTH_CODES)

        assert not df.empty
        assert (df['Centene_Capacity_Plan_State'] == 'TX').all()
        assert df['Client_Forecast_Month1'].iloc[0] == 100

    def test_mmp_forecast_values_extracted(self):
        """MMP sheet provides forecast values."""
        dfs = {
            "medicare_medicaid_nonmmp": {},
            "medicare_medicaid_mmp": {
                "AMISYS MMP Domestic": _make_mmp_df(),
            },
            "medicare_medicaid_summary": {},
            "medicare_medicaid_aligned_dual": {},
        }
        pre = _pre()
        with patch('code.logics.target_cph_utils.get_all_target_cph_as_dict', return_value={}):
            df = pre.extract_forecast_demand(dfs, MONTH_CODES)

        assert not df.empty
        assert df['Client_Forecast_Month1'].iloc[0] == 50

    def test_summary_forecast_values_extracted(self):
        """Summary sheet provides forecast values (state = N/A)."""
        dfs = {
            "medicare_medicaid_nonmmp": {},
            "medicare_medicaid_mmp": {},
            "medicare_medicaid_summary": {
                "Amisys Medicare Non-MMP Global": _make_summary_df("Amisys Medicare"),
            },
            "medicare_medicaid_aligned_dual": {},
        }
        pre = _pre()
        with patch('code.logics.target_cph_utils.get_all_target_cph_as_dict', return_value={}):
            df = pre.extract_forecast_demand(dfs, MONTH_CODES)

        assert not df.empty
        assert (df['Centene_Capacity_Plan_State'] == 'N/A').all()
        assert df['Client_Forecast_Month1'].iloc[0] == 200

    def test_aligned_dual_forecast_values_extracted(self):
        """Aligned Dual sheet provides forecast values."""
        dfs = {
            "medicare_medicaid_nonmmp": {},
            "medicare_medicaid_mmp": {},
            "medicare_medicaid_summary": {},
            "medicare_medicaid_aligned_dual": {
                "AMISYS Aligned Dual Medicare Global": _make_aligned_dual_df(),
            },
        }
        pre = _pre()
        with patch('code.logics.target_cph_utils.get_all_target_cph_as_dict', return_value={}):
            df = pre.extract_forecast_demand(dfs, MONTH_CODES)

        assert not df.empty
        assert df['Client_Forecast_Month1'].iloc[0] == 30

    def test_empty_dfs_returns_empty_dataframe(self):
        """All empty sheet dicts → empty output DataFrame."""
        dfs = {
            "medicare_medicaid_nonmmp": {},
            "medicare_medicaid_mmp": {},
            "medicare_medicaid_summary": {},
            "medicare_medicaid_aligned_dual": {},
        }
        pre = _pre()
        with patch('code.logics.target_cph_utils.get_all_target_cph_as_dict', return_value={}):
            df = pre.extract_forecast_demand(dfs, MONTH_CODES)

        assert df.empty

    def test_target_cph_populated_from_lookup(self):
        """Target CPH is set from lookup dict when available.

        The lob key in the lookup is derived from the sheet dict key passed to
        _extract_summary_demand, which uses lob_name.split('-summary')[0].strip().lower().
        For sheet key 'Amisys Medicare Non-MMP Global' the lob becomes
        'amisys medicare non-mmp global'.
        """
        sheet_key = "Amisys Medicare Non-MMP Global"
        lob_lower = sheet_key.split("-summary")[0].strip().lower()
        lookup = {(lob_lower, "ftc"): 45.0}
        dfs = {
            "medicare_medicaid_nonmmp": {},
            "medicare_medicaid_mmp": {},
            "medicare_medicaid_summary": {
                sheet_key: _make_summary_df("Amisys Medicare"),
            },
            "medicare_medicaid_aligned_dual": {},
        }
        pre = _pre()
        with patch('code.logics.target_cph_utils.get_all_target_cph_as_dict', return_value=lookup):
            df = pre.extract_forecast_demand(dfs, MONTH_CODES, target_cph_lookup=lookup)

        assert not df.empty
        assert df['Centene_Capacity_Plan_Target_CPH'].iloc[0] == 45.0

    def test_missing_target_cph_defaults_to_zero(self):
        """Rows with no matching CPH entry get Target CPH = 0."""
        dfs = {
            "medicare_medicaid_nonmmp": {
                "Amisys Medicaid DOMESTIC": _make_nonmmp_df(),
            },
            "medicare_medicaid_mmp": {},
            "medicare_medicaid_summary": {},
            "medicare_medicaid_aligned_dual": {},
        }
        pre = _pre()
        with patch('code.logics.target_cph_utils.get_all_target_cph_as_dict', return_value={}):
            df = pre.extract_forecast_demand(dfs, MONTH_CODES)

        assert (df['Centene_Capacity_Plan_Target_CPH'] == 0).all()

    def test_combined_sheets_aggregate_rows(self):
        """Multiple sheet types produce rows from all sources."""
        pre = _pre()
        with patch('code.logics.target_cph_utils.get_all_target_cph_as_dict', return_value={}):
            df = pre.extract_forecast_demand(_full_dfs(), MONTH_CODES)

        lobs = df['Centene_Capacity_Plan_Main_LOB'].unique()
        # Rows from at least 2 distinct LOB sources (nonmmp + summary)
        assert len(lobs) >= 2, f"Expected rows from multiple LOB sources, got: {lobs}"


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

    # Output types

    def test_month_is_string(self):
        result = self._parse("forecast_June_2025.xlsx")
        assert isinstance(result["Month"], str)

    def test_year_is_string(self):
        result = self._parse("forecast_June_2025.xlsx")
        assert isinstance(result["Year"], str)

    def test_month_is_capitalized(self):
        result = self._parse("forecast_june_2025.xlsx")
        assert result["Month"] == result["Month"].capitalize()
