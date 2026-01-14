"""
Check if cell values are in the shared strings table instead of inline.
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


def check_shared_strings():
    """Check shared strings table for our header values."""
    print("\n" + "=" * 70)
    print("CHECKING SHARED STRINGS TABLE")
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
        print("\n2. Files in Excel archive:")
        for name in zip_ref.namelist():
            print(f"   - {name}")

        # Read shared strings
        try:
            shared_strings_xml = zip_ref.read('xl/sharedStrings.xml')
            print("\n3. Shared strings table found:")

            root = ET.fromstring(shared_strings_xml)
            ns = {'': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

            for idx, si in enumerate(root.findall('.//{%s}si' % ns[''], ns)):
                t = si.find('.//{%s}t' % ns[''], ns)
                if t is not None:
                    print(f"   [{idx}]: {t.text}")

        except KeyError:
            print("\n3. ✗ No sharedStrings.xml found")

        # Now check worksheet to see cell references
        print("\n4. Checking worksheet cell references (rows 1-2):")
        sheet_xml = zip_ref.read('xl/worksheets/sheet1.xml')
        root = ET.fromstring(sheet_xml)
        ns = {'': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

        for row_elem in root.findall('.//{%s}row' % ns[''], ns):
            row_num = row_elem.get('r')

            if row_num and int(row_num) <= 2:
                print(f"\n   Row {row_num}:")

                for cell_elem in row_elem.findall('.//{%s}c' % ns[''], ns):
                    cell_ref = cell_elem.get('r')
                    cell_type = cell_elem.get('t')  # s = shared string, str = inline string

                    value_elem = cell_elem.find('.//{%s}v' % ns[''], ns)

                    if value_elem is not None:
                        value = value_elem.text
                        if cell_type == 's':
                            print(f"     {cell_ref}: shared string index {value}")
                        else:
                            print(f"     {cell_ref}: inline value '{value}' (type={cell_type})")
                    else:
                        print(f"     {cell_ref}: NO value element (type={cell_type})")

    print("\n" + "=" * 70)
    print("DIAGNOSIS:")
    print("=" * 70)
    print("If cells show 'NO value element', the XML is missing actual content.")
    print("This would cause Excel to need repair.")


if __name__ == "__main__":
    try:
        check_shared_strings()
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
