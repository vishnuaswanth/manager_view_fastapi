"""
Dump the full XML of row 1 to see exactly what's there.
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
import xml.etree.ElementTree as ET


def dump_row1_xml():
    """Dump full XML of row 1."""
    print("\n" + "=" * 70)
    print("DUMPING FULL XML OF ROW 1")
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
            field_name="Jun-25.fte_avail",
            old_value=20,
            new_value=25,
            delta=5,
            month_label="Jun-25"
        )
    ]

    print("\n1. Generating Excel...")
    excel_buffer = generate_history_excel(history_log, changes)
    excel_buffer.seek(0)

    with zipfile.ZipFile(excel_buffer, 'r') as zip_ref:
        sheet_xml = zip_ref.read('xl/worksheets/sheet1.xml')

    # Parse and pretty print
    root = ET.fromstring(sheet_xml)
    ns = {'': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

    print("\n2. Full XML of row 1:\n")

    # Find row 1
    for row_elem in root.findall('.//{%s}row' % ns[''], ns):
        if row_elem.get('r') == '1':
            # Pretty print this row element
            print(ET.tostring(row_elem, encoding='unicode'))
            break

    print("\n3. Full XML of row 2:\n")

    # Find row 2
    for row_elem in root.findall('.//{%s}row' % ns[''], ns):
        if row_elem.get('r') == '2':
            # Pretty print this row element
            print(ET.tostring(row_elem, encoding='unicode'))
            break


if __name__ == "__main__":
    try:
        dump_row1_xml()
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
