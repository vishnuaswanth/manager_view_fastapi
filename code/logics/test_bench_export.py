import pandas as pd
from code.logics.core_utils import CoreUtils
from code.logics.bench_allocation import allocate_bench_for_month
from code.logics.bench_allocation_export import create_changes_workbook
from code.main import DATABASE_URL  # Assuming this exists
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fetch_forecast_by_id(forecast_id: int, core_utils: CoreUtils) -> dict:
    """
    Fetch complete forecast record by ID from database.
    Returns dict with all ForecastModel columns.
    """
    from code.logics.db import ForecastModel

    # Get database session through core_utils
    db_manager = core_utils.get_db_manager(ForecastModel, limit=1, skip=0)

    # Query by ID using the session
    result = db_manager.session.query(ForecastModel).filter(ForecastModel.id == forecast_id).first()

    if not result:
        raise ValueError(f"Forecast record with ID {forecast_id} not found")

    # Convert to dict with all columns
    return {
        'forecast_id': result.id,
        'main_lob': result.Centene_Capacity_Plan_Main_LOB,
        'state': result.Centene_Capacity_Plan_State,
        'case_type': result.Centene_Capacity_Plan_Case_Type,
        'call_type_id': result.Centene_Capacity_Plan_Call_Type_ID,
        'target_cph': result.Centene_Capacity_Plan_Target_CPH,
        'Client_Forecast_Month1': result.Client_Forecast_Month1,
        'Client_Forecast_Month2': result.Client_Forecast_Month2,
        'Client_Forecast_Month3': result.Client_Forecast_Month3,
        'Client_Forecast_Month4': result.Client_Forecast_Month4,
        'Client_Forecast_Month5': result.Client_Forecast_Month5,
        'Client_Forecast_Month6': result.Client_Forecast_Month6,
        'FTE_Required_Month1': result.FTE_Required_Month1,
        'FTE_Required_Month2': result.FTE_Required_Month2,
        'FTE_Required_Month3': result.FTE_Required_Month3,
        'FTE_Required_Month4': result.FTE_Required_Month4,
        'FTE_Required_Month5': result.FTE_Required_Month5,
        'FTE_Required_Month6': result.FTE_Required_Month6,
        'FTE_Avail_Month1': result.FTE_Avail_Month1,
        'FTE_Avail_Month2': result.FTE_Avail_Month2,
        'FTE_Avail_Month3': result.FTE_Avail_Month3,
        'FTE_Avail_Month4': result.FTE_Avail_Month4,
        'FTE_Avail_Month5': result.FTE_Avail_Month5,
        'FTE_Avail_Month6': result.FTE_Avail_Month6,
        'Capacity_Month1': result.Capacity_Month1,
        'Capacity_Month2': result.Capacity_Month2,
        'Capacity_Month3': result.Capacity_Month3,
        'Capacity_Month4': result.Capacity_Month4,
        'Capacity_Month5': result.Capacity_Month5,
        'Capacity_Month6': result.Capacity_Month6,
        'Month': result.Month,
        'Year': result.Year,
        'UploadedFile': result.UploadedFile,
        'CreatedBy': result.CreatedBy,
        'CreatedDateTime': result.CreatedDateTime,
        'UpdatedBy': result.UpdatedBy,
        'UpdatedDateTime': result.UpdatedDateTime
    }

def test_bench_allocation_export(month="March", year=2025):
    """
    Test function to run bench allocation for a specific month/year
    and export the results to Excel files in the logics folder.

    This function does NOT update the database.
    """
    logger.info(f"Starting test bench allocation for {month} {year}")

    # Initialize CoreUtils
    core_utils = CoreUtils(DATABASE_URL)

    # 1. Run allocation logic
    # This reads from DB but returns a result dict (doesn't write to DB)
    result = allocate_bench_for_month(month, year, core_utils)

    if not result['success']:
        logger.error(f"Allocation failed: {result.get('error')}")
        return

    logger.info("Allocation logic completed successfully.")

    # 2. Prepare data for 'modified forecast' Excel
    # The result['allocations'] is now a consolidated list of dicts.
    # Each dict has 'forecast_row' (with updated values), 'vendors', etc.

    modified_rows = []
    changes_detail = []
    vendor_assignments = []

    # Track unique forecast IDs to avoid duplicates
    processed_forecast_ids = set()

    for alloc in result['allocations']:
        row = alloc['forecast_row']
        forecast_id = row['forecast_id']

        # Only process each forecast_id once (avoid duplicate rows)
        if forecast_id in processed_forecast_ids:
            # Still need to process changes_detail and vendor_assignments
            # but skip modified_rows
            pass
        else:
            processed_forecast_ids.add(forecast_id)

            # Fetch complete forecast record from database with all 6 months
            try:
                complete_record = fetch_forecast_by_id(forecast_id, core_utils)
            except ValueError as e:
                logger.error(f"Could not fetch forecast record {forecast_id}: {e}")
                continue

            # Get the month index for this allocation
            m_idx = row['month_index']

            # Build modified row with all 6 months of data
            modified_row = {
                'Centene Capacity Plan Main LOB': complete_record['main_lob'],
                'Centene Capacity Plan State': complete_record['state'],
                'Centene Capacity Plan Case Type': complete_record['case_type'],
                'Centene Capacity Plan Call Type ID': complete_record.get('call_type_id'),
                'Centene Capacity Plan Target CPH': complete_record.get('target_cph'),

                # All 6 months of Client Forecast (from database)
                'Client Forecast Month1': complete_record.get('Client_Forecast_Month1'),
                'Client Forecast Month2': complete_record.get('Client_Forecast_Month2'),
                'Client Forecast Month3': complete_record.get('Client_Forecast_Month3'),
                'Client Forecast Month4': complete_record.get('Client_Forecast_Month4'),
                'Client Forecast Month5': complete_record.get('Client_Forecast_Month5'),
                'Client Forecast Month6': complete_record.get('Client_Forecast_Month6'),

                # All 6 months of FTE Required (from database)
                'FTE Required Month1': complete_record.get('FTE_Required_Month1'),
                'FTE Required Month2': complete_record.get('FTE_Required_Month2'),
                'FTE Required Month3': complete_record.get('FTE_Required_Month3'),
                'FTE Required Month4': complete_record.get('FTE_Required_Month4'),
                'FTE Required Month5': complete_record.get('FTE_Required_Month5'),
                'FTE Required Month6': complete_record.get('FTE_Required_Month6'),

                # All 6 months of FTE Avail (from database)
                'FTE Avail Month1': complete_record.get('FTE_Avail_Month1'),
                'FTE Avail Month2': complete_record.get('FTE_Avail_Month2'),
                'FTE Avail Month3': complete_record.get('FTE_Avail_Month3'),
                'FTE Avail Month4': complete_record.get('FTE_Avail_Month4'),
                'FTE Avail Month5': complete_record.get('FTE_Avail_Month5'),
                'FTE Avail Month6': complete_record.get('FTE_Avail_Month6'),

                # All 6 months of Capacity (from database)
                'Capacity Month1': complete_record.get('Capacity_Month1'),
                'Capacity Month2': complete_record.get('Capacity_Month2'),
                'Capacity Month3': complete_record.get('Capacity_Month3'),
                'Capacity Month4': complete_record.get('Capacity_Month4'),
                'Capacity Month5': complete_record.get('Capacity_Month5'),
                'Capacity Month6': complete_record.get('Capacity_Month6'),

                'Month': complete_record['Month'],
                'Year': complete_record['Year'],
                'UploadedFile': complete_record.get('UploadedFile'),
                'UpdatedBy': 'Bench Allocation Test',
                'UpdatedDateTime': None
            }

            # Update the specific allocated month with modified values
            modified_row[f'FTE Avail Month{m_idx}'] = row['fte_avail']
            modified_row[f'Capacity Month{m_idx}'] = row['capacity']

            modified_rows.append(modified_row)

        capacity_before = row.get('capacity_original', row['capacity'])
        capacity_change = alloc.get('capacity_change', 0)
        capacity_pct_change = (capacity_change / capacity_before) if capacity_before else 0

        # Structure for Changes Detail Sheet
        change = {
            'main_lob': row['main_lob'],
            'state': row['state'],
            'case_type': row['case_type'],
            'month': row['month_name'],
            'fte_required': row['fte_required'],
            'fte_avail_before': row['fte_avail_original'],
            'fte_avail_after': row['fte_avail'],
            'fte_change': alloc['fte_change'],
            'allocation_type': f"Gap: {alloc['gap_fill_count']}, Excess: {alloc['excess_distribution_count']}",
            'vendors_allocated': len(alloc['vendors']),
            'capacity_before': capacity_before,
            'capacity_after': row['capacity'],
            'capacity_change': capacity_change,
            'capacity_pct_change': capacity_pct_change
        }
        changes_detail.append(change)

        # Structure for Vendor Assignments Sheet
        for vendor in alloc['vendors']:
            assignment = {
                'vendor_name': f"{vendor.get('first_name')} {vendor.get('last_name')}",
                'vendor_cn': vendor.get('cn'),
                'vendor_skills': vendor.get('skills'),
                'vendor_states': ", ".join(vendor.get('state_list', [])),
                'allocated_to_lob': row['main_lob'],
                'allocated_to_state': row['state'],
                'allocated_to_worktype': row['case_type'],
                'allocation_month': row['month_name'],
                'allocation_type': "Bench"
            }
            vendor_assignments.append(assignment)

    # Convert to DataFrame
    modified_forecast_df = pd.DataFrame(modified_rows)

    # 3. Create Summary Dict
    summary = {
        'month': month,
        'year': year,
        'total_bench_allocated': result['total_bench_allocated'],
        'gaps_filled': result['gaps_filled'],
        'excess_distributed': result['excess_distributed'],
        'rows_modified': result['rows_modified'],
        'validation': {'valid': True} # Assuming valid since it ran
    }

    # 4. Generate Export Excel
    # Using the existing export logic
    output_dir = os.path.join(os.getcwd(), 'code', 'logics')
    excel_path = create_changes_workbook(
        changes=changes_detail,
        summary=summary,
        modified_forecast_rows=modified_forecast_df,
        vendor_assignments=vendor_assignments,
        output_dir=output_dir
    )

    logger.info(f"Bench allocation export created at: {excel_path}")

    # Note: Roster Model and Buckets After Allocation are typically generated
    # inside the 'allocator' class in allocation.py. bench_allocation.py uses a different logic.
    # The 'vendor_assignments' sheet in the workbook above serves as the updated roster list
    # for the bench vendors specifically.

if __name__ == "__main__":
    test_bench_allocation_export()
