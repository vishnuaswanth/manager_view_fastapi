import pandas as pd
from code.core_utils import CoreUtils
from code.logics.bench_allocation import allocate_bench_for_month
from code.logics.bench_allocation_export import create_changes_workbook
from code.settings import DATABASE_URL  # Assuming this exists
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    
    for alloc in result['allocations']:
        row = alloc['forecast_row']
        
        # Structure for Modified Forecast Sheet (matches download format roughly)
        # Note: ForecatModel has Month1-Month6. The forecast_row is unnormalized (single month).
        # To truly match download format, we'd need to map this back to 6-month wide format,
        # but for this test/debug export, we'll dump the relevant single-month data.
        modified_row = {
            'Centene Capacity Plan Main LOB': row['main_lob'],
            'Centene Capacity Plan State': row['state'],
            'Centene Capacity Plan Case Type': row['case_type'],
            'Month': row['month_name'],
            'Year': row['month_year'],
            'FTE Required': row['fte_required'],
            'FTE Avail (Old)': row['fte_avail_original'],
            'FTE Avail (New)': row['fte_avail'],
            'Capacity (Old)': row['capacity'] - alloc.get('capacity_change', 0),
            'Capacity (New)': row['capacity']
        }
        modified_rows.append(modified_row)
        
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
            'capacity_before': row['capacity'] - alloc.get('capacity_change', 0),
            'capacity_after': row['capacity'],
            'capacity_change': alloc.get('capacity_change', 0)
        }
        changes_detail.append(change)
        
        # Structure for Vendor Assignments Sheet
        for vendor in alloc['vendors']:
            assignment = {
                'vendor_name': f"{vendor.get('first_name')} {vendor.get('last_name')}",
                'vendor_cn': vendor.get('cn'),
                'vendor_skills': vendor.get('skills'),
                'allocated_to_lob': row['main_lob'],
                'allocated_to_state': row['state'],
                'allocated_to_worktype': row['case_type']
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
