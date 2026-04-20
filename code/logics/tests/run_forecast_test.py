"""
Standalone forecast file validation script.

Simulates the forecast upload pipeline (parse → extract demand → build output Excel)
WITHOUT requiring database access or API calls. Use this to validate new forecast
file variations locally before uploading.

Usage:
    python code/logics/tests/run_forecast_test.py "path/to/forecast.xlsx"
    python code/logics/tests/run_forecast_test.py "path/to/forecast.xlsx" "output.xlsx"

Or from Python:
    from code.logics.tests.run_forecast_test import run_forecast_test
    run_forecast_test("NTT Forecast - Capacity HC - March_2026.xlsx")
"""

import os
import sys
import pandas as pd
from io import BytesIO
from typing import Optional, Dict


def run_forecast_test(file_path: str, output_path: Optional[str] = None) -> str:
    """
    Simulate forecast upload pipeline and generate forecast report Excel.

    Processes the file exactly as the upload endpoint would, extracts demand,
    and writes a forecast report Excel using the same template as the download
    endpoint. No database access required.

    Args:
        file_path: Path to forecast Excel file.
        output_path: Where to save the output Excel. Defaults to
                     <input_file_without_ext>_forecast_report.xlsx.

    Returns:
        Path to the generated output Excel file.

    Raises:
        ValueError: If month/year cannot be extracted from filename or no demand found.
        FileNotFoundError: If the file does not exist.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    from code.logics.core_utils import PreProcessing
    from code.logics.export_utils import (
        export_with_total_formatting,
        add_totals_row_by_index,
        month_columns_by_level,
    )

    pre = PreProcessing("forecast")

    # ─── 1. Extract month/year from filename ──────────────────────────────────
    month_year = pre.get_month_year(os.path.basename(file_path))
    if not month_year:
        raise ValueError(
            f"Cannot extract month/year from filename: {file_path}\n"
            "Expected format like: 'NTT Forecast - March_2026.xlsx'"
        )
    month, year = month_year["Month"], month_year["Year"]
    print(f"Detected: {month} {year}")

    # ─── 2. Parse all sheets (same as upload endpoint) ───────────────────────
    print("Parsing forecast file sheets...")
    dfs = pre.process_forecast_file(file_path)
    month_codes = pre.month_codes  # {"Month1": "April", ..., "Month6": "September"}
    print(f"Months: {list(month_codes.values())}")
    print(f"Sheet models found: {list(dfs.keys())}")
    for model, subdict in dfs.items():
        print(f"  {model}: {list(subdict.keys())}")

    # ─── 3. Extract normalized demand (no DB needed) ─────────────────────────
    print("Extracting forecast demand...")
    demand_df = pre.extract_forecast_demand(dfs, month_codes, target_cph_lookup={})
    # target_cph_lookup={} → no DB required; Target CPH will be 0 in test output

    if demand_df.empty:
        raise ValueError("No forecast demand extracted from file. Check sheet structure.")

    print(f"Extracted {len(demand_df)} demand rows")
    print(f"LOBs (first 10): {demand_df['Centene_Capacity_Plan_Main_LOB'].unique()[:10].tolist()}")
    print(f"States (first 10): {demand_df['Centene_Capacity_Plan_State'].unique()[:10].tolist()}")

    # ─── 4. Build MultiIndex output DataFrame ─────────────────────────────────
    output_df = _build_multiindex_output(demand_df, month_codes)

    # ─── 5. Add totals row and export ─────────────────────────────────────────
    indexes = month_columns_by_level(output_df)
    mod_df, total_row = add_totals_row_by_index(output_df, indexes, label_col_idx=0)
    stream = export_with_total_formatting(mod_df, total_row, header_offset=3)

    # ─── 6. Save output ───────────────────────────────────────────────────────
    if output_path is None:
        base = os.path.splitext(file_path)[0]
        output_path = f"{base}_forecast_report.xlsx"

    with open(output_path, "wb") as f:
        f.write(stream.getvalue())

    print(f"\nForecast report saved to: {output_path}")
    return output_path


def validate_forecast_file(file_path: str) -> Dict:
    """
    Validate forecast file structure and return a summary report.

    Does NOT require database access. Returns a dict with:
        - success: bool
        - month: str
        - year: str
        - sheet_models: dict  {model: [lob_names...]}
        - row_counts: dict    {model: count}
        - total_rows: int
        - errors: list[str]
        - warnings: list[str]

    Args:
        file_path: Path to the forecast Excel file.

    Returns:
        Validation report dictionary.
    """
    from code.logics.core_utils import PreProcessing

    errors = []
    warnings = []
    result = {
        "success": False,
        "month": None,
        "year": None,
        "sheet_models": {},
        "row_counts": {},
        "total_rows": 0,
        "errors": errors,
        "warnings": warnings,
    }

    if not os.path.exists(file_path):
        errors.append(f"File not found: {file_path}")
        return result

    pre = PreProcessing("forecast")

    # Check month/year in filename
    month_year = pre.get_month_year(os.path.basename(file_path))
    if not month_year:
        errors.append("Cannot extract month/year from filename. Expected format: 'forecast_March_2026.xlsx'")
        return result

    result["month"] = month_year["Month"]
    result["year"] = month_year["Year"]

    # Parse sheets
    try:
        dfs = pre.process_forecast_file(file_path)
        month_codes = pre.month_codes
    except ValueError as ve:
        errors.append(f"Sheet validation error: {ve}")
        return result
    except Exception as e:
        errors.append(f"Unexpected error parsing file: {e}")
        return result

    # Check each model
    total_rows = 0
    for model, subdict in dfs.items():
        lob_names = list(subdict.keys())
        result["sheet_models"][model] = lob_names
        if not lob_names:
            warnings.append(f"Model '{model}' has no sub-tables.")

    # Extract demand
    try:
        demand_df = pre.extract_forecast_demand(dfs, month_codes, target_cph_lookup={})
    except Exception as e:
        errors.append(f"Demand extraction error: {e}")
        return result

    if demand_df.empty:
        errors.append("No demand rows extracted. Check sheet structure.")
        return result

    # Count rows per LOB
    for lob, group in demand_df.groupby("Centene_Capacity_Plan_Main_LOB"):
        result["row_counts"][lob] = len(group)

    total_rows = len(demand_df)
    result["total_rows"] = total_rows

    # Check for zero-forecast rows
    forecast_cols = [f"Client_Forecast_Month{i}" for i in range(1, 7)]
    zero_mask = demand_df[forecast_cols].sum(axis=1) == 0
    zero_count = zero_mask.sum()
    if zero_count > 0:
        warnings.append(f"{zero_count} rows have zero forecast across all months.")

    # Check months
    if len(month_codes) < 6:
        errors.append(f"Expected 6 months, found {len(month_codes)}: {month_codes}")
    else:
        result["months"] = list(month_codes.values())

    result["success"] = len(errors) == 0
    return result


def _build_multiindex_output(demand_df: pd.DataFrame, month_codes: dict) -> pd.DataFrame:
    """
    Convert flat ForecastModel-column DataFrame to MultiIndex format for Excel export.

    Level 0: Centene Capacity plan / Client Forecast / FTE Required / FTE Avail / Capacity
    Level 1: field name or actual month name
    """
    meta_tuples = [
        ("Centene Capacity plan", "Main LOB"),
        ("Centene Capacity plan", "State"),
        ("Centene Capacity plan", "Case type"),
        ("Centene Capacity plan", "Call Type ID"),
        ("Centene Capacity plan", "Target CPH"),
    ]
    meta_flat = [
        "Centene_Capacity_Plan_Main_LOB",
        "Centene_Capacity_Plan_State",
        "Centene_Capacity_Plan_Case_Type",
        "Centene_Capacity_Plan_Call_Type_ID",
        "Centene_Capacity_Plan_Target_CPH",
    ]

    month_tuples = []
    month_flat = []
    # Sections outer, months inner → section-grouped columns so Excel merges
    # each section header across all 6 months (Client Forecast ×6, FTE Required ×6, …)
    for section, prefix in [
        ("Client Forecast", "Client_Forecast"),
        ("FTE Required", "FTE_Required"),
        ("FTE Avail", "FTE_Avail"),
        ("Capacity", "Capacity"),
    ]:
        for m_key, month_name in month_codes.items():
            month_tuples.append((section, month_name))
            month_flat.append(f"{prefix}_{m_key}")

    all_tuples = meta_tuples + month_tuples
    all_flat = meta_flat + month_flat

    output = pd.DataFrame(
        index=demand_df.index,
        columns=pd.MultiIndex.from_tuples(all_tuples),
    )
    for flat_col, multi_col in zip(all_flat, all_tuples):
        if flat_col in demand_df.columns:
            output[multi_col] = demand_df[flat_col].values

    return output.fillna(0)


if __name__ == "__main__":
    fp = sys.argv[1] if len(sys.argv) > 1 else "NTT Forecast - Capacity HC - March_2026.xlsx"
    out = sys.argv[2] if len(sys.argv) > 2 else None

    # Run validation first
    print("=" * 60)
    print("VALIDATION REPORT")
    print("=" * 60)
    report = validate_forecast_file(fp)
    print(f"  Success:    {report['success']}")
    print(f"  Month/Year: {report.get('month')} {report.get('year')}")
    print(f"  Months:     {report.get('months', [])}")
    print(f"  Total rows: {report['total_rows']}")
    if report["errors"]:
        print(f"  ERRORS:")
        for e in report["errors"]:
            print(f"    - {e}")
    if report["warnings"]:
        print(f"  Warnings:")
        for w in report["warnings"]:
            print(f"    - {w}")
    print(f"  Models:")
    for model, lobs in report["sheet_models"].items():
        print(f"    {model}: {lobs}")
    print()

    # Generate Excel report
    if report["success"]:
        print("=" * 60)
        print("GENERATING FORECAST REPORT EXCEL")
        print("=" * 60)
        try:
            output_path = run_forecast_test(fp, out)
            print(f"\nDone! Output: {output_path}")
        except Exception as e:
            print(f"ERROR: {e}")
            sys.exit(1)
    else:
        print("Skipping Excel generation due to validation errors.")
        sys.exit(1)
