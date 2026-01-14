"""Debug why Client Forecast column is missing from Excel."""

import sys
import os
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from code.logics.history_excel_generator import (
    HistoryLogData,
    HistoryChangeRecord,
    _prepare_pivot_data
)


def test_pivot_data_with_all_fields():
    """Test what happens when all 4 fields are in changes list."""
    print("\n" + "=" * 70)
    print("Debug: Pivot Data Generation")
    print("=" * 70)

    # Create changes for ALL 4 fields
    changes = [
        HistoryChangeRecord(
            main_lob="Amisys Medicaid DOMESTIC",
            state="TX",
            case_type="Claims",
            case_id="CL-001",
            field_name="Jun-25.forecast",
            old_value=1000,
            new_value=1000,
            delta=0,
            month_label="Jun-25"
        ),
        HistoryChangeRecord(
            main_lob="Amisys Medicaid DOMESTIC",
            state="TX",
            case_type="Claims",
            case_id="CL-001",
            field_name="Jun-25.fte_req",
            old_value=20,
            new_value=20,
            delta=0,
            month_label="Jun-25"
        ),
        HistoryChangeRecord(
            main_lob="Amisys Medicaid DOMESTIC",
            state="TX",
            case_type="Claims",
            case_id="CL-001",
            field_name="Jun-25.fte_avail",
            old_value=20,
            new_value=25,
            delta=5,
            month_label="Jun-25"
        ),
        HistoryChangeRecord(
            main_lob="Amisys Medicaid DOMESTIC",
            state="TX",
            case_type="Claims",
            case_id="CL-001",
            field_name="Jun-25.capacity",
            old_value=1000,
            new_value=1125,
            delta=125,
            month_label="Jun-25"
        )
    ]

    print(f"\nInput: {len(changes)} change records")
    for i, change in enumerate(changes):
        print(f"  {i+1}. {change.field_name}: {change.old_value} → {change.new_value} (delta={change.delta})")

    # Call _prepare_pivot_data
    pivot_rows, month_labels, static_columns = _prepare_pivot_data(changes)

    print(f"\nOutput: {len(pivot_rows)} pivot rows")
    print(f"Month labels: {month_labels}")
    print(f"Static columns: {static_columns}")

    # Check what fields are in the pivot row
    if pivot_rows:
        row = pivot_rows[0]
        print("\nPivot row keys:")
        for key in row.keys():
            print(f"  - {key}: {row[key]}")

        # Check if all expected columns exist
        expected_columns = [
            "Jun-25 Client Forecast",
            "Jun-25 FTE Required",
            "Jun-25 FTE Available",
            "Jun-25 Capacity"
        ]

        print("\nChecking for expected columns:")
        for col in expected_columns:
            exists = col in row
            symbol = "✓" if exists else "✗"
            value = row.get(col, "MISSING")
            print(f"  {symbol} {col}: {value}")

            if not exists:
                print(f"\n✗ MISSING COLUMN: {col}")
                print("Available columns:")
                for k in row.keys():
                    if "Jun-25" in k:
                        print(f"    - {k}")


if __name__ == "__main__":
    test_pivot_data_with_all_fields()
