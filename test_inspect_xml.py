"""
Inspect the raw XML content of the Excel file to see if None values exist in the XML.
"""

import sys
import os
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from code.logics.history_excel_generator import (
    HistoryLogData,
    HistoryChangeRecord,
    generate_history_excel
)
import zipfile
from io import BytesIO
import xml.etree.ElementTree as ET


def inspect_excel_xml():
    """Inspect the raw XML to see cell values before merge."""
    print("\n" + "=" * 70)
    print("INSPECTING EXCEL XML CONTENT")
    print("=" * 70)

    # Create test data
    history_log = HistoryLogData(
        id="test-001",
        change_type="Bench Allocation",
        month="March",
        year=2025,
        timestamp="2025-03-15T14:30:00Z",
        user="system",
        description="Test",
        records_modified=1,
        summary_data=None
    )

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
            field_name="Jun-25.fte_avail",
            old_value=20,
            new_value=25,
            delta=5,
            month_label="Jun-25"
        )
    ]

    print("\n1. Generating Excel...")
    excel_buffer = generate_history_excel(history_log, changes)
    print("   ✓ Generated")

    # Excel files are ZIP archives
    print("\n2. Extracting XML from Excel (it's a ZIP)...")
    excel_buffer.seek(0)

    with zipfile.ZipFile(excel_buffer, 'r') as zip_ref:
        # Read the worksheet XML
        sheet_xml = zip_ref.read('xl/worksheets/sheet1.xml')

    print("   ✓ Extracted sheet1.xml")

    # Parse XML
    print("\n3. Parsing XML...")
    root = ET.fromstring(sheet_xml)

    # Find namespace
    ns = {'': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    if root.tag.startswith('{'):
        ns_url = root.tag.split('}')[0][1:]
        ns = {'': ns_url}

    print(f"   Namespace: {ns['']}")

    # Find all row elements
    print("\n4. Checking cell values in XML (rows 1-2):")

    for row_elem in root.findall('.//{%s}row' % ns[''], ns):
        row_num = row_elem.get('r')

        if row_num and int(row_num) <= 2:
            print(f"\n   Row {row_num}:")

            for cell_elem in row_elem.findall('.//{%s}c' % ns[''], ns):
                cell_ref = cell_elem.get('r')

                # Check for value element
                value_elem = cell_elem.find('.//{%s}v' % ns[''], ns)

                if value_elem is not None:
                    # Cell has a value in XML
                    print(f"     {cell_ref}: has <v> element (value exists in XML)")
                else:
                    # Cell has no value element
                    print(f"     {cell_ref}: NO <v> element (no value in XML)")

    # Check for merged cells definition
    print("\n5. Checking mergedCells definition:")
    merged_cells = root.find('.//{%s}mergeCells' % ns[''], ns)

    if merged_cells is not None:
        print(f"   ✓ Found mergeCells element")
        for merge_cell in merged_cells.findall('.//{%s}mergeCell' % ns[''], ns):
            ref = merge_cell.get('ref')
            print(f"     - {ref}")
    else:
        print("   ✗ No mergeCells element found")

    print("\n" + "=" * 70)
    print("KEY INSIGHT:")
    print("=" * 70)
    print("If cells in merged ranges have NO <v> element in XML,")
    print("Excel might consider this invalid and trigger repair.")
    print("\nOur fix writes the same value to all cells BEFORE merging,")
    print("so all cells should have <v> elements in the XML.")


if __name__ == "__main__":
    try:
        inspect_excel_xml()
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
