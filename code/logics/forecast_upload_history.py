"""
History logging for forecast uploads and modifications.

Handles tracking changes when forecast data is uploaded or altered, supporting
the CHANGE_TYPE_FORECAST_UPDATE change type for two scenarios:
1. Initial forecast upload (allocation.py → process_files())
2. Altered forecast upload (upload_router.py → /upload/altered_forecast)
"""

import logging
import pandas as pd
from typing import Dict, List, Optional, Tuple

from code.logics.db import ForecastModel
from code.logics.core_utils import CoreUtils
from code.logics.edit_view_utils import get_months_dict
from code.logics.history_logger import create_history_log, add_history_changes
from code.logics.config.change_types import CHANGE_TYPE_FORECAST_UPDATE

logger = logging.getLogger(__name__)


def capture_forecast_snapshot(
    month: str,
    year: int,
    core_utils: CoreUtils
) -> Optional[pd.DataFrame]:
    """
    Capture current forecast data from database before upload/modification.

    Returns None if no existing data (new upload scenario).

    Args:
        month: Report month name (e.g., "April")
        year: Report year (e.g., 2025)
        core_utils: CoreUtils instance for database access

    Returns:
        DataFrame with current forecast data or None if no existing data
    """
    try:
        db_manager = core_utils.get_db_manager(
            ForecastModel,
            limit=100000,
            skip=0,
            select_columns=None
        )

        with db_manager.SessionLocal() as session:
            records = session.query(ForecastModel).filter(
                ForecastModel.Month == month,
                ForecastModel.Year == year
            ).all()

            if not records:
                logger.info(f"No existing forecast data for {month} {year} (new upload)")
                return None

            # Convert to DataFrame with standard column names
            data = []
            for record in records:
                row = {
                    'Main_LOB': record.Main_LOB,
                    'State': record.State,
                    'Case_Type': record.Case_Type,
                    'Case_ID': record.Case_ID,
                    'Target_CPH': record.Target_CPH,
                }

                # Add Month1-Month6 fields
                for suffix in ['1', '2', '3', '4', '5', '6']:
                    row[f'Client_Forecast_Month{suffix}'] = getattr(record, f'Client_Forecast_Month{suffix}', 0) or 0
                    row[f'FTE_Required_Month{suffix}'] = getattr(record, f'FTE_Required_Month{suffix}', 0) or 0
                    row[f'FTE_Avail_Month{suffix}'] = getattr(record, f'FTE_Avail_Month{suffix}', 0) or 0
                    row[f'Capacity_Month{suffix}'] = getattr(record, f'Capacity_Month{suffix}', 0) or 0

                data.append(row)

            df = pd.DataFrame(data)
            logger.info(f"Captured forecast snapshot: {len(df)} records for {month} {year}")
            return df

    except Exception as e:
        logger.error(f"Failed to capture forecast snapshot: {e}", exc_info=True)
        return None


def compare_forecast_snapshots(
    before_df: Optional[pd.DataFrame],
    after_df: pd.DataFrame,
    months_dict: Dict[str, str]
) -> Tuple[List[Dict], int]:
    """
    Compare before/after forecast DataFrames and identify changes.

    Returns modified_records in same format as bench allocation for consistency.

    Handles two cases:
    1. No before_df (new upload): All records are "new", change = value
    2. With before_df: Compare old vs new, calculate deltas

    Args:
        before_df: Snapshot before upload (None for new uploads)
        after_df: Snapshot after upload
        months_dict: Month index mapping (e.g., {"month1": "Jun-25"})

    Returns:
        Tuple of (modified_records list, total_modified count)
    """
    modified_records = []

    # CASE 1: New upload (no previous data)
    if before_df is None or before_df.empty:
        logger.info("No previous data - treating all records as new")

        for _, row in after_df.iterrows():
            record = {
                "main_lob": row.get('Main_LOB', ''),
                "state": row.get('State', ''),
                "case_type": row.get('Case_Type', ''),
                "case_id": row.get('Case_ID', ''),
                "target_cph": row.get('Target_CPH', 0),
                "target_cph_change": row.get('Target_CPH', 0),
                "modified_fields": []
            }

            # Track target_cph
            if row.get('Target_CPH', 0) != 0:
                record["modified_fields"].append("target_cph")

            # Add month data
            for month_idx, month_label in months_dict.items():
                suffix = month_idx.replace('month', '')  # "month1" → "1"

                forecast = row.get(f'Client_Forecast_Month{suffix}', 0) or 0
                fte_req = row.get(f'FTE_Required_Month{suffix}', 0) or 0
                fte_avail = row.get(f'FTE_Avail_Month{suffix}', 0) or 0
                capacity = row.get(f'Capacity_Month{suffix}', 0) or 0

                record[month_label] = {
                    "forecast": forecast,
                    "fte_req": fte_req,
                    "fte_avail": fte_avail,
                    "capacity": capacity,
                    "forecast_change": forecast,      # New upload: change = value
                    "fte_req_change": fte_req,
                    "fte_avail_change": fte_avail,
                    "capacity_change": capacity
                }

                # Track non-zero fields
                if forecast != 0:
                    record["modified_fields"].append(f"{month_label}.forecast")
                if fte_req != 0:
                    record["modified_fields"].append(f"{month_label}.fte_req")
                if fte_avail != 0:
                    record["modified_fields"].append(f"{month_label}.fte_avail")
                if capacity != 0:
                    record["modified_fields"].append(f"{month_label}.capacity")

            # Include all records for new upload
            modified_records.append(record)

        return modified_records, len(modified_records)

    # CASE 2: Update (compare old vs new)
    # Merge on composite key
    merged = after_df.merge(
        before_df,
        on=['Main_LOB', 'State', 'Case_Type', 'Case_ID'],
        how='left',
        suffixes=('_new', '_old')
    )

    for _, row in merged.iterrows():
        record = {
            "main_lob": row.get('Main_LOB', ''),
            "state": row.get('State', ''),
            "case_type": row.get('Case_Type', ''),
            "case_id": row.get('Case_ID', ''),
            "target_cph": row.get('Target_CPH_new', 0),
            "target_cph_change": 0,
            "modified_fields": []
        }

        # Check target_cph change
        old_cph = row.get('Target_CPH_old', 0) if pd.notna(row.get('Target_CPH_old')) else 0
        new_cph = row.get('Target_CPH_new', 0)
        cph_change = new_cph - old_cph

        if cph_change != 0:
            record["target_cph_change"] = cph_change
            record["modified_fields"].append("target_cph")

        # Check month data changes
        for month_idx, month_label in months_dict.items():
            suffix = month_idx.replace('month', '')

            # Get new values
            forecast_new = row.get(f'Client_Forecast_Month{suffix}_new', 0) or 0
            fte_req_new = row.get(f'FTE_Required_Month{suffix}_new', 0) or 0
            fte_avail_new = row.get(f'FTE_Avail_Month{suffix}_new', 0) or 0
            capacity_new = row.get(f'Capacity_Month{suffix}_new', 0) or 0

            # Get old values (may be NaN if row is new)
            forecast_old = row.get(f'Client_Forecast_Month{suffix}_old', 0)
            forecast_old = forecast_old if pd.notna(forecast_old) else 0

            fte_req_old = row.get(f'FTE_Required_Month{suffix}_old', 0)
            fte_req_old = fte_req_old if pd.notna(fte_req_old) else 0

            fte_avail_old = row.get(f'FTE_Avail_Month{suffix}_old', 0)
            fte_avail_old = fte_avail_old if pd.notna(fte_avail_old) else 0

            capacity_old = row.get(f'Capacity_Month{suffix}_old', 0)
            capacity_old = capacity_old if pd.notna(capacity_old) else 0

            # Calculate changes
            forecast_change = forecast_new - forecast_old
            fte_req_change = fte_req_new - fte_req_old
            fte_avail_change = fte_avail_new - fte_avail_old
            capacity_change = capacity_new - capacity_old

            record[month_label] = {
                "forecast": forecast_new,
                "fte_req": fte_req_new,
                "fte_avail": fte_avail_new,
                "capacity": capacity_new,
                "forecast_change": forecast_change,
                "fte_req_change": fte_req_change,
                "fte_avail_change": fte_avail_change,
                "capacity_change": capacity_change
            }

            # Track modified fields
            if forecast_change != 0:
                record["modified_fields"].append(f"{month_label}.forecast")
            if fte_req_change != 0:
                record["modified_fields"].append(f"{month_label}.fte_req")
            if fte_avail_change != 0:
                record["modified_fields"].append(f"{month_label}.fte_avail")
            if capacity_change != 0:
                record["modified_fields"].append(f"{month_label}.capacity")

        # Only include if there are changes
        if record["modified_fields"]:
            modified_records.append(record)

    return modified_records, len(modified_records)


def create_forecast_upload_history_log(
    month: str,
    year: int,
    user: str,
    description: Optional[str],
    before_df: Optional[pd.DataFrame],
    after_df: pd.DataFrame,
    core_utils: CoreUtils
) -> Dict:
    """
    Create history log for forecast upload/modification.

    This is the main entry point - orchestrates the full process:
    1. Get month mappings
    2. Compare before/after snapshots
    3. Extract specific changes (REUSE bench allocation function)
    4. Calculate summary data (REUSE bench allocation function)
    5. Create history log
    6. Add history changes

    Args:
        month: Report month name (e.g., "April")
        year: Report year (e.g., 2025)
        user: User identifier who uploaded the file
        description: Optional description (e.g., filename)
        before_df: DataFrame before upload (None for new uploads)
        after_df: DataFrame after upload
        core_utils: CoreUtils instance

    Returns:
        Dict with success, history_log_id, records_modified, error
    """
    try:
        # Get month mappings
        months_dict = get_months_dict(month, year, core_utils)

        # Compare snapshots
        modified_records, total_modified = compare_forecast_snapshots(
            before_df,
            after_df,
            months_dict
        )

        if total_modified == 0:
            logger.info(f"No changes detected for {month} {year}")
            return {
                'success': True,
                'history_log_id': None,
                'records_modified': 0,
                'message': 'No changes to log'
            }

        # REUSE bench allocation functions (DRY principle)
        from code.logics.bench_allocation_transformer import (
            extract_specific_changes,
            calculate_summary_data
        )

        changes = extract_specific_changes(modified_records, months_dict)
        summary_data = calculate_summary_data(modified_records, months_dict, month, year)

        # Create history log
        history_log_id = create_history_log(
            month=month,
            year=year,
            change_type=CHANGE_TYPE_FORECAST_UPDATE,
            user=user,
            description=description or "Forecast data uploaded",
            records_modified=total_modified,
            summary_data=summary_data
        )

        # Add history changes
        add_history_changes(history_log_id, changes)

        logger.info(
            f"Created forecast upload history log: {history_log_id} "
            f"for {month} {year}, {total_modified} records modified"
        )

        return {
            'success': True,
            'history_log_id': history_log_id,
            'records_modified': total_modified
        }

    except Exception as e:
        logger.error(f"Failed to create forecast upload history log: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'records_modified': 0
        }
