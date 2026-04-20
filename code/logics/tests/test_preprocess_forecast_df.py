"""
Tests for PreProcessing.preprocess_forecast_df column mapping correctness.

The allocation write-back path is:
    allocation.py → preprocess_forecast_df(consolidated_df) → update_forecast_data()

consolidated_df comes from get_forecast_demand_from_db(), which builds a
**month-grouped** MultiIndex (months outer, sections inner):
    (CF, Apr) | (FTE_Req, Apr) | (FTE_Avail, Apr) | (Cap, Apr) | (CF, May) | ...

MAPPING['forecast'] is **section-grouped**:
    CF_Month1..6 | FTE_Req_Month1..6 | FTE_Avail_Month1..6 | Cap_Month1..6

A positional df.columns = MAPPING assignment silently stores April's FTE_Required
into Client_Forecast_Month2, April's FTE_Avail into Client_Forecast_Month3, etc.

These tests verify that preprocess_forecast_df maps each section+month to the
correct DB column regardless of MultiIndex column order.
"""

import pytest
import pandas as pd
from code.logics.core_utils import PreProcessing


MONTHS = ["April", "May", "June", "July", "August", "September"]

# Sentinel base values per section — distinct ranges so a mismap is immediately visible
_CF_BASE  = 100
_FTE_BASE = 200
_FAV_BASE = 300
_CAP_BASE = 400


def _make_month_grouped_multiindex_df():
    """
    Build a 1-row MultiIndex DataFrame exactly as get_forecast_demand_from_db() returns:
    month-grouped columns (months outer, sections inner).

    Sentinel values: section_base + month_index (1-6).
    e.g. CF April=101, FTE_Req April=201, FTE_Avail April=301, Capacity April=401
         CF May=102,   FTE_Req May=202,   ...
    """
    meta_tuples = [
        ("Centene Capacity plan", "Main LOB"),
        ("Centene Capacity plan", "State"),
        ("Centene Capacity plan", "Case type"),
        ("Centene Capacity plan", "Call Type ID"),
        ("Centene Capacity plan", "Target CPH"),
    ]
    meta_values = ["Amisys Medicare", "TX", "FTC", "amisys ftc", 50]

    month_tuples = []
    month_values = []
    for idx, month_name in enumerate(MONTHS, start=1):
        for section, base in [
            ("Client Forecast", _CF_BASE),
            ("FTE Required",    _FTE_BASE),
            ("FTE Avail",       _FAV_BASE),
            ("Capacity",        _CAP_BASE),
        ]:
            month_tuples.append((section, month_name))
            month_values.append(base + idx)

    all_tuples = meta_tuples + month_tuples
    all_values = meta_values + month_values

    df = pd.DataFrame(
        [all_values],
        columns=pd.MultiIndex.from_tuples(all_tuples),
    )
    return df


class TestPreprocessForecastDf:

    def _run(self):
        pre = PreProcessing("forecast")
        df = _make_month_grouped_multiindex_df()
        return pre.preprocess_forecast_df(df)

    def test_output_has_all_expected_db_columns(self):
        result = self._run()
        expected = PreProcessing("forecast").MAPPING["forecast"]
        assert list(result.columns) == expected

    def test_client_forecast_months_map_to_correct_db_columns(self):
        result = self._run()
        row = result.iloc[0]
        for m_idx in range(1, 7):
            val = row[f"Client_Forecast_Month{m_idx}"]
            expected = _CF_BASE + m_idx
            assert val == expected, (
                f"Client_Forecast_Month{m_idx}: expected {expected}, got {val}. "
                f"A different section's value was mapped into this column."
            )

    def test_fte_required_months_map_to_correct_db_columns(self):
        result = self._run()
        row = result.iloc[0]
        for m_idx in range(1, 7):
            val = row[f"FTE_Required_Month{m_idx}"]
            expected = _FTE_BASE + m_idx
            assert val == expected, (
                f"FTE_Required_Month{m_idx}: expected {expected}, got {val}. "
                f"CF or FTE_Avail value leaked into FTE_Required column."
            )

    def test_fte_avail_months_map_to_correct_db_columns(self):
        result = self._run()
        row = result.iloc[0]
        for m_idx in range(1, 7):
            val = row[f"FTE_Avail_Month{m_idx}"]
            expected = _FAV_BASE + m_idx
            assert val == expected, (
                f"FTE_Avail_Month{m_idx}: expected {expected}, got {val}."
            )

    def test_capacity_months_map_to_correct_db_columns(self):
        result = self._run()
        row = result.iloc[0]
        for m_idx in range(1, 7):
            val = row[f"Capacity_Month{m_idx}"]
            expected = _CAP_BASE + m_idx
            assert val == expected, (
                f"Capacity_Month{m_idx}: expected {expected}, got {val}."
            )

    def test_meta_columns_mapped_correctly(self):
        result = self._run()
        row = result.iloc[0]
        assert row["Centene_Capacity_Plan_Main_LOB"] == "Amisys Medicare"
        assert row["Centene_Capacity_Plan_State"] == "TX"
        assert row["Centene_Capacity_Plan_Case_Type"] == "FTC"
        assert row["Centene_Capacity_Plan_Call_Type_ID"] == "amisys ftc"
        assert row["Centene_Capacity_Plan_Target_CPH"] == 50

    def test_april_cf_is_101_not_fte_value(self):
        """Spot-check: Month1 (April) CF must be 101, not 201 (FTE_Req)."""
        result = self._run()
        assert result.iloc[0]["Client_Forecast_Month1"] == 101

    def test_april_fte_required_is_201_not_cf_value(self):
        """Spot-check: Month1 (April) FTE_Required must be 201, not 101 (CF)."""
        result = self._run()
        assert result.iloc[0]["FTE_Required_Month1"] == 201

    def test_september_capacity_is_406(self):
        """Spot-check: Month6 (September) Capacity must be 406."""
        result = self._run()
        assert result.iloc[0]["Capacity_Month6"] == 406
