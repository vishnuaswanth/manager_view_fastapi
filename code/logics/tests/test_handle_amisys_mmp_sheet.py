"""
Unit tests for PreProcessing._handle_amisys_mmp_sheet(), specifically the
Area-missing fallback path's Table 1 / Table 2 boundary detection.

Regression coverage for a bug where, when the "Area" column is absent (so the
handler falls back to deriving Global/Domestic from State), the Table 1 end
boundary was computed by scanning "Forecast"-labeled columns across the whole
sheet instead of stopping before Table 2. If Table 2 (Capacity/Vendor HC) also
has a "Forecast"-labeled column, that pulled Table 2 into work_type_cols and
doubled every row produced for the sheet.
"""

import io
import pytest
import pandas as pd

from code.logics.core_utils import PreProcessing


def _mmp_sheet_bytes(include_area: bool, include_table2_forecast_col: bool) -> bytes:
    """Build a minimal MMP-style sheet: 3 header rows + 1 data row.

    Table 1: one work-type Forecast column, Month, State (Area only if requested).
    Table 2 (mirrors Month/State right after Table 1): optionally has its own
    "Forecast"-labeled column (the leak vector for the fallback boundary bug).
    """
    if include_area:
        h0 = ["FTC", "", "", "", ""]
        h1 = ["FTC-Medicare MMP", "", "", "", ""]
        h2 = ["Forecast", "Month", "State", "Area", "Month"]
        data = [[50, "April", "MI", "Domestic", "April"]]
        # Table 2 tail (State + optional Forecast) appended below
        h0.append(""); h1.append(""); h2.append("State")
        data[0].append("MI")
        if include_table2_forecast_col:
            h0.append("TBL2"); h1.append("Vendor HC"); h2.append("Forecast")
            data[0].append(999)
    else:
        h0 = ["FTC", "", "", "TBL2", ""]
        h1 = ["FTC-Medicare MMP", "", "", "", ""]
        h2 = ["Forecast", "Month", "State", "Month", "State"]
        data = [[50, "April", "MI", "April", "MI"]]
        if include_table2_forecast_col:
            h0.append("TBL2"); h1.append("Vendor HC"); h2.append("Forecast")
            data[0].append(999)

    grid = pd.DataFrame([h0, h1, h2] + data)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        grid.to_excel(writer, sheet_name="Amisys MMP State Level", index=False, header=False)
    return buf.getvalue()


def _pre():
    return PreProcessing("forecast")


class TestMmpFallbackBoundary:

    def test_area_present_table2_forecast_col_not_leaked(self):
        """Baseline: Area column present → boundary is safe regardless of Table 2."""
        content = _mmp_sheet_bytes(include_area=True, include_table2_forecast_col=True)
        df = _pre()._handle_amisys_mmp_sheet(
            io.BytesIO(content), "Amisys MMP State Level",
            month_codes={"Month1": "April"}, month_name_to_key={}, target_cph_lookup={},
        )
        assert len(df) == 1

    def test_area_missing_no_table2_forecast_col_single_row(self):
        """Fallback engages, but Table 2 has no 'Forecast' column → no leak, no dup."""
        content = _mmp_sheet_bytes(include_area=False, include_table2_forecast_col=False)
        df = _pre()._handle_amisys_mmp_sheet(
            io.BytesIO(content), "Amisys MMP State Level",
            month_codes={"Month1": "April"}, month_name_to_key={}, target_cph_lookup={},
        )
        assert len(df) == 1

    def test_area_missing_table2_forecast_col_does_not_duplicate_row(self):
        """Regression: fallback + a 'Forecast'-labeled Table 2 column used to double
        the row count (Table 1 real row + Table 2 leaked row). Must stay at 1."""
        content = _mmp_sheet_bytes(include_area=False, include_table2_forecast_col=True)
        df = _pre()._handle_amisys_mmp_sheet(
            io.BytesIO(content), "Amisys MMP State Level",
            month_codes={"Month1": "April"}, month_name_to_key={}, target_cph_lookup={},
        )
        assert len(df) == 1, (
            f"Expected exactly 1 row (Table 2 must not leak into work_type_cols), got {len(df)}:\n"
            f"{df[['Centene_Capacity_Plan_Main_LOB', 'Centene_Capacity_Plan_State', 'Centene_Capacity_Plan_Case_Type']]}"
        )
        assert df["Client_Forecast_Month1"].iloc[0] == 50  # Table 1's real value, not Table 2's 999
