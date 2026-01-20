"""
Forecast data update functions for Edit View operations.

Handles updating ForecastModel records with changes from bench allocation,
CPH updates, and other edit operations.
"""

import logging
from typing import Dict, List
from code.logics.db import ForecastModel
from code.logics.core_utils import CoreUtils
from code.logics.edit_view_utils import (
    get_forecast_column_name,
    extract_month_suffix_from_index,
    reverse_months_dict,
    parse_field_path
)

logger = logging.getLogger(__name__)


def update_forecast_from_modified_records(
    modified_records: List[Dict],
    months_dict: Dict[str, str],
    report_month: str,
    report_year: int,
    core_utils: CoreUtils,
    operation_type: str = "update"
) -> bool:
    """
    Update ForecastModel records with forecast modifications.

    Generic updater used by both bench allocation and CPH update operations.
    Uses composite filtering with ALL identifying fields (Main_LOB, State, Case_Type,
    Call_Type_ID, Month, Year) to ensure precise record matching and prevent
    unintended updates.

    Args:
        modified_records: List of ModifiedForecastRecord dicts with changes. Each record must contain:
            - main_lob: Centene_Capacity_Plan_Main_LOB
            - state: Centene_Capacity_Plan_State
            - case_type: Centene_Capacity_Plan_Case_Type
            - case_id: Centene_Capacity_Plan_Call_Type_ID
            - modified_fields: List of field paths to update
            - Month-specific data for updates
        months_dict: Month index mapping ({"month1": "Jun-25", ...})
        report_month: Report month name
        report_year: Report year
        core_utils: CoreUtils instance
        operation_type: Type of operation for logging (e.g., "bench_allocation", "cph_update")

    Returns:
        True if successful

    Raises:
        ValueError: If forecast records not found or required fields missing
        SQLAlchemyError: If database update fails
    """
    try:
        db_manager = core_utils.get_db_manager(
            ForecastModel,
            limit=10000,
            skip=0,
            select_columns=None
        )

        # Reverse month mapping for lookup: {"Jun-25": "month1", ...}
        month_label_to_index = reverse_months_dict(months_dict)

        with db_manager.SessionLocal() as session:
            # Process each modified record
            for i, record in enumerate(modified_records):
                # Validate required fields
                required_fields = ["main_lob", "state", "case_type", "case_id"]
                missing_fields = [field for field in required_fields if field not in record]
                if missing_fields:
                    raise ValueError(
                        f"Record at index {i} missing required fields: {missing_fields}"
                    )

                # Extract all identifying fields for precise filtering
                main_lob = record["main_lob"]
                state = record["state"]
                case_type = record["case_type"]
                call_type_id = record["case_id"]

                logger.debug(
                    f"Searching for forecast record: LOB={main_lob}, State={state}, "
                    f"CaseType={case_type}, CallTypeID={call_type_id}, "
                    f"Month={report_month}, Year={report_year}"
                )

                # Find forecast record using ALL identifying fields for robust filtering
                forecast_record = session.query(ForecastModel).filter(
                    ForecastModel.Centene_Capacity_Plan_Main_LOB == main_lob,
                    ForecastModel.Centene_Capacity_Plan_State == state,
                    ForecastModel.Centene_Capacity_Plan_Case_Type == case_type,
                    ForecastModel.Centene_Capacity_Plan_Call_Type_ID == call_type_id,
                    ForecastModel.Month == report_month,
                    ForecastModel.Year == report_year
                ).first()

                if not forecast_record:
                    from code.logics.exceptions import ForecastRecordNotFoundException

                    logger.error(
                        f"Forecast record not found: Main_LOB={main_lob}, State={state}, "
                        f"Case_Type={case_type}, Call_Type_ID={call_type_id}, "
                        f"Month={report_month}, Year={report_year}"
                    )
                    raise ForecastRecordNotFoundException(
                        main_lob, state, case_type, call_type_id,
                        report_month, report_year
                    )

                logger.debug(
                    f"Found forecast record ID={forecast_record.id} for "
                    f"CallTypeID={call_type_id}"
                )

                # Parse modified_fields and update
                for field_path in record.get("modified_fields", []):
                    # Parse field path using utility function
                    month_label, field_name = parse_field_path(field_path)

                    if month_label:
                        # Month-specific field: "Jun-25.fte_avail"
                        month_index = month_label_to_index.get(month_label)

                        if not month_index:
                            logger.warning(f"Unknown month label: {month_label}")
                            continue

                        # Extract month suffix
                        month_suffix = extract_month_suffix_from_index(month_index)

                        # Get new value from record
                        month_data = record.get(month_label, {})
                        new_value = month_data.get(field_name)

                        if new_value is None:
                            logger.warning(f"No value for {field_path}")
                            continue

                        # Get ForecastModel column name
                        column_name = get_forecast_column_name(field_name, month_suffix)
                        if not column_name:
                            logger.warning(f"Unknown field: {field_name}")
                            continue

                        # Update the column
                        setattr(forecast_record, column_name, new_value)
                        logger.info(
                            f"Updated {column_name} = {new_value} for "
                            f"CallTypeID={call_type_id}, LOB={main_lob}, State={state}"
                        )

                    else:
                        # Month-agnostic field: "target_cph"
                        new_value = record.get(field_path)

                        if field_path == "target_cph":
                            forecast_record.Centene_Capacity_Plan_Target_CPH = new_value
                            logger.info(
                                f"Updated Target_CPH = {new_value} for "
                                f"CallTypeID={call_type_id}, LOB={main_lob}, State={state}"
                            )

            # Commit all updates
            session.commit()
            logger.info(f"Successfully updated {len(modified_records)} forecast records")
            return True

    except Exception as e:
        logger.error(f"Failed to update forecast data: {e}", exc_info=True)
        raise
