"""
History Excel Export Generator.

Generates Excel files for history log downloads with pivot table format
showing before/after values for forecast changes.
"""

import logging
import pandas as pd
from io import BytesIO
from typing import Dict, List, Optional
from openpyxl import load_workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)


def generate_history_excel(
    history_log_data: Dict,
    changes: List[Dict]
) -> BytesIO:
    """
    Generate Excel file for history log download.

    Args:
        history_log_data: History log metadata dict with:
            - id: history_log_id
            - change_type: Type of change
            - month: Report month
            - year: Report year
            - timestamp: ISO timestamp
            - user: User who made change
            - description: Optional notes
            - records_modified: Count
            - summary_data: Optional summary dict
        changes: List of field-level change dicts with:
            - main_lob: str
            - state: str
            - case_type: str
            - case_id: str
            - field_name: str (DOT notation)
            - old_value: str/None
            - new_value: str/None
            - delta: float/None
            - month_label: str/None

    Returns:
        BytesIO: Excel file buffer

    Raises:
        ValueError: If data is invalid
    """
    if not changes:
        raise ValueError("No changes provided for Excel generation")

    # Step 1: Transform changes to pivot table structure
    pivot_data = _prepare_pivot_data(changes)

    # Step 2: Create Excel workbook with openpyxl
    excel_buffer = BytesIO()

    # Step 3: Create main data sheet
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        # Write pivot data
        df_pivot = pd.DataFrame(pivot_data)
        df_pivot.to_excel(writer, sheet_name='Changes', index=False)

        # Write summary sheet
        summary_data = _prepare_summary_sheet(history_log_data)
        df_summary = pd.DataFrame(summary_data)
        df_summary.to_excel(writer, sheet_name='Summary', index=False, header=False)

    # Step 4: Apply formatting with openpyxl
    excel_buffer.seek(0)
    _apply_formatting(excel_buffer, history_log_data)

    excel_buffer.seek(0)
    logger.info(f"Generated Excel for history log {history_log_data['id']}")
    return excel_buffer


def _prepare_pivot_data(changes: List[Dict]) -> List[Dict]:
    """
    Transform changes list to pivot table structure.

    Groups changes by forecast record (main_lob, state, case_type, case_id)
    and creates columns for each month+field combination.

    Returns:
        List of row dicts with structure:
        {
            "Main LOB": "...",
            "State": "...",
            "Case Type": "...",
            "Case ID": "...",
            "Jun-25 Client Forecast": "12500",
            "Jun-25 FTE Required": "25.5",
            "Jun-25 FTE Available": "28.0 (25.0)",  # new (old) if changed
            "Jun-25 Capacity": "1400 (1250)",
            "Jul-25 Client Forecast": "...",
            ...
        }
    """
    # Group changes by forecast record
    grouped_changes = {}

    for change in changes:
        key = (
            change['main_lob'],
            change['state'],
            change['case_type'],
            change['case_id']
        )

        if key not in grouped_changes:
            grouped_changes[key] = {
                'main_lob': change['main_lob'],
                'state': change['state'],
                'case_type': change['case_type'],
                'case_id': change['case_id'],
                'fields': {}
            }

        # Parse field path
        field_name = change['field_name']

        # Determine display name
        if '.' in field_name:
            # Month-specific field: "Jun-25.fte_avail"
            month_label, metric = field_name.split('.', 1)
            metric_display = _get_metric_display_name(metric)
            column_name = f"{month_label} {metric_display}"
        else:
            # Month-agnostic field: "target_cph"
            column_name = _get_metric_display_name(field_name)

        # Format value (show old in brackets if changed)
        old_val = change.get('old_value')
        new_val = change.get('new_value')

        if old_val is not None and new_val is not None and str(old_val) != str(new_val):
            display_value = f"{new_val} ({old_val})"
        else:
            display_value = new_val if new_val is not None else old_val

        grouped_changes[key]['fields'][column_name] = display_value

    # Convert to list of row dicts
    pivot_rows = []
    for (main_lob, state, case_type, case_id), record in grouped_changes.items():
        row = {
            'Main LOB': main_lob,
            'State': state,
            'Case Type': case_type,
            'Case ID': case_id
        }
        row.update(record['fields'])
        pivot_rows.append(row)

    return pivot_rows


def _get_metric_display_name(metric: str) -> str:
    """Convert API metric name to display name."""
    metric_map = {
        'forecast': 'Client Forecast',
        'fte_req': 'FTE Required',
        'fte_avail': 'FTE Available',
        'capacity': 'Capacity',
        'target_cph': 'Target CPH'
    }
    return metric_map.get(metric, metric.replace('_', ' ').title())


def _prepare_summary_sheet(history_log_data: Dict) -> List[Dict]:
    """
    Prepare summary sheet data.

    Returns:
        List of {label: value} dicts for vertical layout
    """
    summary_rows = [
        {'label': 'History Log ID', 'value': history_log_data['id']},
        {'label': 'Change Type', 'value': history_log_data['change_type']},
        {'label': 'Report Month', 'value': f"{history_log_data['month']} {history_log_data['year']}"},
        {'label': 'Timestamp', 'value': history_log_data['timestamp']},
        {'label': 'User', 'value': history_log_data['user']},
        {'label': 'Description', 'value': history_log_data.get('description') or 'N/A'},
        {'label': 'Records Modified', 'value': str(history_log_data['records_modified'])},
    ]

    # Add summary data if present
    if history_log_data.get('summary_data'):
        summary_rows.append({'label': '', 'value': ''})  # Blank row
        summary_rows.append({'label': 'SUMMARY TOTALS', 'value': ''})

        summary_data = history_log_data['summary_data']
        if 'totals' in summary_data:
            for month_label, totals in summary_data['totals'].items():
                summary_rows.append({'label': f"{month_label} Total FTE Available (Old)", 'value': str(totals.get('total_fte_available', {}).get('old', 0))})
                summary_rows.append({'label': f"{month_label} Total FTE Available (New)", 'value': str(totals.get('total_fte_available', {}).get('new', 0))})

    return summary_rows


def _apply_formatting(excel_buffer: BytesIO, history_log_data: Dict):
    """
    Apply openpyxl formatting to Excel workbook.

    Args:
        excel_buffer: BytesIO with Excel data
        history_log_data: History log metadata for filename/titles
    """
    wb = load_workbook(excel_buffer)

    # Format Changes sheet
    if 'Changes' in wb.sheetnames:
        ws_changes = wb['Changes']

        # Define styles
        header_font = Font(bold=True, size=11)
        header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )

        # Apply header formatting
        for cell in ws_changes[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = border

        # Apply borders to all cells
        for row in ws_changes.iter_rows(min_row=2, max_row=ws_changes.max_row, max_col=ws_changes.max_column):
            for cell in row:
                cell.border = border
                cell.alignment = Alignment(horizontal='left', vertical='top')

        # Auto-size columns
        for column in ws_changes.columns:
            max_length = 0
            column_letter = get_column_letter(column[0].column)

            for cell in column:
                try:
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))
                except:
                    pass

            adjusted_width = min(max_length + 2, 50)  # Cap at 50
            ws_changes.column_dimensions[column_letter].width = adjusted_width

    # Format Summary sheet
    if 'Summary' in wb.sheetnames:
        ws_summary = wb['Summary']

        # Bold first column (labels)
        for row in ws_summary.iter_rows(min_row=1, max_row=ws_summary.max_row):
            row[0].font = Font(bold=True)

        # Auto-size
        for column in ws_summary.columns:
            max_length = 0
            column_letter = get_column_letter(column[0].column)

            for cell in column:
                try:
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))
                except:
                    pass

            ws_summary.column_dimensions[column_letter].width = max_length + 2

    # Save changes
    wb.save(excel_buffer)
    logger.info("Applied Excel formatting successfully")
