"""
Pytest tests for PreProcessing.process_forecast_file sheet-handling behavior.

Covers:
  - All sheets present → full processing, no errors
  - Individual detail sheet missing → skipped gracefully, rest processed
  - All optional sheets missing → only summary processed
  - Sheet present but corrupt/unreadable → HTTP 400 with actionable message
  - No months found in summary → HTTP 400
  - Summary unknown platform → HTTP 400

Architecture note (new):
  Each handler _handle_*_sheet now returns pd.DataFrame (not Dict[str, DataFrame]).
  detail handlers signature: (file_stream, sheet_name, month_codes, month_name_to_key, target_cph_lookup) -> pd.DataFrame
  summary handler: _handle_summary_sheet(raw_summary_dfs, month_codes, month_name_to_key, target_cph_lookup) -> pd.DataFrame
  referenced_sheets list from extract_summary_tables drives which detail handlers run.
"""

import io
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from fastapi import HTTPException

from code.logics.core_utils import PreProcessing


# ─── Shared sheet name constants ──────────────────────────────────────────────

SHEET_AMISYS_MEDICAID_DOMESTIC = "Amisys Medicaid DOMESTIC"
SHEET_AMISYS_MEDICAID_GLOBAL   = "Amisys Medicaid GLOBAL"
SHEET_MMP                      = "Amisys MMP State Level"
SHEET_SUMMARY                  = "Forecast v Capacity Summary"
SHEET_ALIGNED_DUAL             = "Amisys Aligned Dual State Level"

ALL_SHEETS = [
    SHEET_AMISYS_MEDICAID_DOMESTIC, SHEET_AMISYS_MEDICAID_GLOBAL,
    SHEET_MMP, SHEET_SUMMARY, SHEET_ALIGNED_DUAL,
]

ALL_REFERENCED = [
    SHEET_AMISYS_MEDICAID_DOMESTIC, SHEET_AMISYS_MEDICAID_GLOBAL,
    SHEET_MMP, SHEET_ALIGNED_DUAL,
]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _pre():
    return PreProcessing("forecast")


def _make_forecast_df(lob="TestLOB"):
    """Minimal ForecastModel DataFrame (handler output format)."""
    pre = PreProcessing("forecast")
    cols = pre.MAPPING["forecast"]
    row = {
        "Centene_Capacity_Plan_Main_LOB": lob,
        "Centene_Capacity_Plan_State": "TX",
        "Centene_Capacity_Plan_Case_Type": "FTC",
        "Centene_Capacity_Plan_Call_Type_ID": f"{lob} ftc",
        "Centene_Capacity_Plan_Target_CPH": 0.0,
    }
    for i in range(1, 7):
        row[f"Client_Forecast_Month{i}"] = 100
        row[f"FTE_Required_Month{i}"] = 0
        row[f"FTE_Avail_Month{i}"] = 0
        row[f"Capacity_Month{i}"] = 0
    return pd.DataFrame([row], columns=cols)


def _make_summary_raw_dfs():
    """Minimal summary raw DataFrames as returned by extract_summary_tables.
    Must have 4-level MultiIndex columns with 'CPH' and month names at level 2.
    """
    cols = pd.MultiIndex.from_tuples([
        ('Amisys Medicare', 'Amisys Medicare', 'Work Type', 'Work Type'),
        ('Amisys Medicare', 'Amisys Medicare', 'CPH', 'CPH'),
        ('Amisys Medicare', 'Amisys Medicare', 'April', 'April'),
    ])
    data = [['FTC', 10, 200]]
    df = pd.DataFrame(data, columns=cols)
    return {'Amisys Medicare Non-MMP Global': df}


def _mock_excel_file(sheet_names):
    mock_xl = MagicMock()
    mock_xl.sheet_names = sheet_names
    return mock_xl


def _empty_forecast_df():
    pre = PreProcessing("forecast")
    return pd.DataFrame(columns=pre.MAPPING["forecast"])


# ─── Tests: all sheets processed / missing sheets skipped gracefully ──────────

class TestMissingSheetsSkipped:

    def _run(self, available_sheets, referenced_sheets=None):
        """
        Run process_forecast_file with a controlled set of available/referenced sheets.
        Patches handlers so no real Excel I/O happens.
        referenced_sheets defaults to all detail sheets (ALL_REFERENCED).
        """
        if referenced_sheets is None:
            referenced_sheets = [s for s in ALL_REFERENCED if s in available_sheets]

        pre = _pre()

        def _detail_handler_side_effect(file_stream, sheet_name, month_codes, month_name_to_key, target_cph_lookup):
            return _make_forecast_df(lob=sheet_name)

        with patch('pandas.ExcelFile', return_value=_mock_excel_file(available_sheets)), \
             patch('code.logics.core_utils.extract_summary_tables',
                   return_value=(_make_summary_raw_dfs(), referenced_sheets)), \
             patch.object(pre, '_handle_summary_sheet', return_value=_make_forecast_df("Amisys Medicare")), \
             patch.object(pre, '_handle_amisys_medicaid_sheet', side_effect=_detail_handler_side_effect), \
             patch.object(pre, '_handle_amisys_mmp_sheet', side_effect=_detail_handler_side_effect), \
             patch.object(pre, '_handle_amisys_aligned_dual_sheet', side_effect=_detail_handler_side_effect), \
             patch('code.logics.target_cph_utils.get_all_target_cph_as_dict', return_value={}):
            return pre.process_forecast_file(io.BytesIO(b"fake"))

    def test_all_sheets_present_returns_full_result(self):
        dfs = self._run(ALL_SHEETS)
        assert not dfs["summary"].empty
        assert not dfs["amisys_medicaid"].empty
        assert not dfs["amisys_mmp"].empty
        assert not dfs["amisys_aligned_dual"].empty

    def test_amisys_medicaid_domestic_missing_not_processed(self):
        """Medicaid domestic not in available sheets → handler not called for it."""
        sheets = [s for s in ALL_SHEETS if s != SHEET_AMISYS_MEDICAID_DOMESTIC]
        referenced = [s for s in ALL_REFERENCED if s in sheets]
        dfs = self._run(sheets, referenced_sheets=referenced)
        # Medicaid global is still processed
        lobs = set(dfs["amisys_medicaid"]["Centene_Capacity_Plan_Main_LOB"].tolist()) if not dfs["amisys_medicaid"].empty else set()
        assert SHEET_AMISYS_MEDICAID_DOMESTIC not in lobs

    def test_mmp_sheet_missing_leaves_mmp_empty(self):
        sheets = [s for s in ALL_SHEETS if s != SHEET_MMP]
        dfs = self._run(sheets)
        assert dfs.get("amisys_mmp") is None or dfs.get("amisys_mmp", pd.DataFrame()).empty

    def test_aligned_dual_missing_leaves_aligned_dual_empty(self):
        sheets = [s for s in ALL_SHEETS if s != SHEET_ALIGNED_DUAL]
        dfs = self._run(sheets)
        assert dfs.get("amisys_aligned_dual") is None or dfs.get("amisys_aligned_dual", pd.DataFrame()).empty

    def test_only_summary_present_still_works(self):
        """File has only the summary sheet — detail handlers not called."""
        dfs = self._run([SHEET_SUMMARY], referenced_sheets=[])
        assert not dfs["summary"].empty
        # Detail sheets not in dfs (or empty) — no KeyError
        assert dfs.get("amisys_medicaid") is None or dfs.get("amisys_medicaid", pd.DataFrame()).empty

    def test_month_codes_set_after_processing(self):
        pre = _pre()

        def _detail_handler(_fs, sheet, mc, mnk, cph_lkp):
            return _make_forecast_df(lob=sheet)

        with patch('pandas.ExcelFile', return_value=_mock_excel_file(ALL_SHEETS)), \
             patch('code.logics.core_utils.extract_summary_tables',
                   return_value=(_make_summary_raw_dfs(), ALL_REFERENCED)), \
             patch.object(pre, '_handle_summary_sheet', return_value=_make_forecast_df("Amisys Medicare")), \
             patch.object(pre, '_handle_amisys_medicaid_sheet', side_effect=_detail_handler), \
             patch.object(pre, '_handle_amisys_mmp_sheet', side_effect=_detail_handler), \
             patch.object(pre, '_handle_amisys_aligned_dual_sheet', side_effect=_detail_handler), \
             patch('code.logics.target_cph_utils.get_all_target_cph_as_dict', return_value={}):
            pre.process_forecast_file(io.BytesIO(b"fake"))

        assert hasattr(pre, 'month_codes')
        assert len(pre.month_codes) == 6

    def test_sheet_in_registry_but_not_referenced_not_processed(self):
        """A known sheet in available_sheets but NOT in referenced_sheets is skipped."""
        dfs = self._run(ALL_SHEETS, referenced_sheets=[])  # no detail sheets referenced
        # All detail sheets should be absent or empty
        for key in ("amisys_medicaid", "amisys_mmp", "amisys_aligned_dual"):
            assert dfs.get(key) is None or dfs.get(key, pd.DataFrame()).empty


# ─── Tests: parse failures raise HTTP 400 with clear messages ─────────────────

class TestParseFailuresRaiseHTTP400:

    def _run_with_handler_error(self, failing_handler_name, failing_sheet=None):
        """Helper: patch one handler to raise, others succeed."""
        pre = _pre()

        def _ok_handler(_fs, sheet, mc, mnk, cph_lkp):
            return _make_forecast_df(lob=sheet)

        def _failing_handler(_fs, sheet, mc, mnk, cph_lkp):
            if failing_sheet is None or sheet == failing_sheet:
                raise ValueError("Simulated parse error")
            return _make_forecast_df(lob=sheet)

        handler_patches = {
            "_handle_amisys_medicaid_sheet": _ok_handler,
            "_handle_amisys_mmp_sheet":       _ok_handler,
            "_handle_amisys_aligned_dual_sheet": _ok_handler,
        }
        handler_patches[failing_handler_name] = _failing_handler

        with patch('pandas.ExcelFile', return_value=_mock_excel_file(ALL_SHEETS)), \
             patch('code.logics.core_utils.extract_summary_tables',
                   return_value=(_make_summary_raw_dfs(), ALL_REFERENCED)), \
             patch.object(pre, '_handle_summary_sheet', return_value=_make_forecast_df("Amisys Medicare")), \
             patch.object(pre, '_handle_amisys_medicaid_sheet', side_effect=handler_patches["_handle_amisys_medicaid_sheet"]), \
             patch.object(pre, '_handle_amisys_mmp_sheet', side_effect=handler_patches["_handle_amisys_mmp_sheet"]), \
             patch.object(pre, '_handle_amisys_aligned_dual_sheet', side_effect=handler_patches["_handle_amisys_aligned_dual_sheet"]), \
             patch('code.logics.target_cph_utils.get_all_target_cph_as_dict', return_value={}):
            with pytest.raises(HTTPException) as exc_info:
                pre.process_forecast_file(io.BytesIO(b"fake"))
        return exc_info.value

    def test_amisys_medicaid_parse_error_raises_400(self):
        exc = self._run_with_handler_error("_handle_amisys_medicaid_sheet")
        assert exc.status_code == 400
        assert "parsed" in str(exc.detail).lower() or "error" in str(exc.detail).lower()

    def test_mmp_parse_error_raises_400(self):
        exc = self._run_with_handler_error("_handle_amisys_mmp_sheet")
        assert exc.status_code == 400

    def test_aligned_dual_parse_error_raises_400(self):
        exc = self._run_with_handler_error("_handle_amisys_aligned_dual_sheet")
        assert exc.status_code == 400

    def test_summary_parse_error_raises_400(self):
        pre = _pre()
        with patch('pandas.ExcelFile', return_value=_mock_excel_file(ALL_SHEETS)), \
             patch('code.logics.core_utils.extract_summary_tables',
                   side_effect=RuntimeError("Table headers shifted")):
            with pytest.raises(HTTPException) as exc_info:
                pre.process_forecast_file(io.BytesIO(b"fake"))
        assert exc_info.value.status_code == 400
        assert SHEET_SUMMARY in str(exc_info.value.detail)

    def test_summary_unknown_platform_raises_400(self):
        pre = _pre()
        bad_summary = {'Unknown Platform LOB': pd.DataFrame()}
        with patch('pandas.ExcelFile', return_value=_mock_excel_file(ALL_SHEETS)), \
             patch('code.logics.core_utils.extract_summary_tables',
                   return_value=(bad_summary, [])):
            with pytest.raises(HTTPException) as exc_info:
                pre.process_forecast_file(io.BytesIO(b"fake"))
        assert exc_info.value.status_code == 400
        assert "platform" in str(exc_info.value.detail).lower()

    def test_summary_sheet_missing_raises_400(self):
        pre = _pre()
        sheets = [s for s in ALL_SHEETS if s != SHEET_SUMMARY]
        with patch('pandas.ExcelFile', return_value=_mock_excel_file(sheets)):
            with pytest.raises(HTTPException) as exc_info:
                pre.process_forecast_file(io.BytesIO(b"fake"))
        assert exc_info.value.status_code == 400
        assert SHEET_SUMMARY in str(exc_info.value.detail)


# ─── Tests: no months in summary → HTTP 400 ──────────────────────────────────

class TestNoMonthsRaisesHTTP400:

    def test_no_months_in_summary_raises_400(self):
        """Summary present but has no month columns → HTTP 400."""
        pre = _pre()
        # Summary df with no month columns (only Work Type and CPH at level 2)
        no_month_summary = {
            'Amisys Medicare': pd.DataFrame(
                [['FTC', 10]],
                columns=pd.MultiIndex.from_tuples([
                    ('A', 'A', 'Work Type', 'Work Type'),
                    ('A', 'A', 'CPH', 'CPH'),
                ])
            )
        }
        with patch('pandas.ExcelFile', return_value=_mock_excel_file(ALL_SHEETS)), \
             patch('code.logics.core_utils.extract_summary_tables',
                   return_value=(no_month_summary, [])):
            with pytest.raises(HTTPException) as exc_info:
                pre.process_forecast_file(io.BytesIO(b"fake"))
        assert exc_info.value.status_code == 400
        assert "month" in str(exc_info.value.detail).lower()
