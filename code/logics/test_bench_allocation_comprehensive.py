"""
Comprehensive Bench Allocation Testing

This file contains all testing functionality for bench allocation in one place:
1. check_allocation_result() - Inspect raw allocation output
2. test_full_export() - Test complete export with all 6 months data

Usage:
    python code/logics/test_bench_allocation_comprehensive.py
"""

import pandas as pd
from code.logics.core_utils import CoreUtils
from code.logics.bench_allocation import allocate_bench_for_month
from code.logics.bench_allocation_export import create_changes_workbook
from code.main import DATABASE_URL
import os
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

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


# ============================================================================
# FUNCTION 1: CHECK ALLOCATION RESULT
# ============================================================================

def check_allocation_result(month="March", year=2025):
    """
    Step 1: Check the raw output from allocate_bench_for_month().

    This function runs the allocation and exports the RAW result to Excel
    for inspection BEFORE dealing with the complex export logic.

    Creates a simple 3-sheet Excel file:
    - Summary: Basic metrics
    - Allocations: Detailed allocation data with forecast_row info
    - Vendors: All vendors allocated

    Returns:
        str: Path to the created Excel file
    """
    logger.info(f"\n{'='*70}")
    logger.info(f"STEP 1: Checking raw allocation result for {month} {year}")
    logger.info(f"{'='*70}\n")

    # Initialize CoreUtils
    core_utils = CoreUtils(DATABASE_URL)

    # Run allocation logic
    logger.info("Running bench allocation...")
    result = allocate_bench_for_month(month, year, core_utils)

    if not result.success:
        logger.error(f"Allocation failed: {result.error}")
        return None

    logger.info("✓ Allocation completed successfully!")
    logger.info(f"  Total bench allocated: {result.total_bench_allocated}")
    logger.info(f"  Gaps filled: {result.gaps_filled}")
    logger.info(f"  Excess distributed: {result.excess_distributed}")
    logger.info(f"  Rows modified: {result.rows_modified}")

    # Prepare data for Excel export
    logger.info("\nPreparing data for Excel export...")
    allocations_data = []
    vendors_data = []

    for idx, alloc in enumerate(result.allocations):
        forecast_row = alloc.forecast_row

        # Main allocation info
        alloc_info = {
            'Index': idx + 1,
            'Forecast ID': forecast_row.forecast_id,
            'Main LOB': forecast_row.main_lob,
            'State': forecast_row.state,
            'Case Type': forecast_row.case_type,
            'Month Name': forecast_row.month_name,
            'Month Year': forecast_row.month_year,
            'Month Index': forecast_row.month_index,
            'Target CPH': forecast_row.target_cph,
            'Forecast': forecast_row.forecast,
            'FTE Required': forecast_row.fte_required,
            'FTE Avail Original': forecast_row.fte_avail_original,
            'FTE Avail After': forecast_row.fte_avail,
            'FTE Change': alloc.fte_change,
            'Capacity Original': forecast_row.capacity_original,
            'Capacity After': forecast_row.capacity,
            'Capacity Change': alloc.capacity_change,
            'Gap Fill Count': alloc.gap_fill_count,
            'Excess Dist Count': alloc.excess_distribution_count,
            'Vendors Count': len(alloc.vendors)
        }
        allocations_data.append(alloc_info)

        # Vendor details
        for vendor in alloc.vendors:
            vendor_info = {
                'Alloc Index': idx + 1,
                'Forecast ID': forecast_row.forecast_id,
                'Vendor Name': f"{vendor.first_name} {vendor.last_name}",
                'Vendor CN': vendor.cn,
                'Vendor Skills': vendor.skills,
                'Vendor States': ', '.join(vendor.state_list),
                'Allocated To LOB': forecast_row.main_lob,
                'Allocated To State': forecast_row.state,
                'Allocated To Case': forecast_row.case_type,
                'Allocation Month': forecast_row.month_name
            }
            vendors_data.append(vendor_info)

    # Convert to DataFrames
    allocations_df = pd.DataFrame(allocations_data)
    vendors_df = pd.DataFrame(vendors_data)

    # # VALIDATION: Check for duplicate allocations and proportional balance
    # logger.info("\nRunning validation checks...")
    # validation_data = []

    # # Check 1: No duplicate allocations (same vendor + same month)
    # if len(vendors_df) > 0 and 'Vendor CN' in vendors_df.columns and 'Allocation Month' in vendors_df.columns:
    #     vendor_month_pairs = vendors_df.groupby(['Vendor CN', 'Allocation Month']).size()
    #     duplicates = vendor_month_pairs[vendor_month_pairs > 1]
    #     validation_data.append({
    #         'Check': 'No Duplicate Allocations',
    #         'Status': 'PASS' if len(duplicates) == 0 else 'FAIL',
    #         'Details': f'{len(duplicates)} duplicates found' if len(duplicates) > 0 else 'No duplicates'
    #     })
    #     if len(duplicates) > 0:
    #         logger.warning(f"⚠️  Found {len(duplicates)} duplicate vendor-month allocations!")
    #         for (cn, month), count in duplicates.items():
    #             logger.warning(f"   - Vendor {cn} allocated {count} times in {month}")
    #     else:
    #         logger.info("✓ No duplicate allocations found")
    # else:
    #     validation_data.append({
    #         'Check': 'No Duplicate Allocations',
    #         'Status': 'N/A',
    #         'Details': 'No vendors to check'
    #     })
    #     logger.info("✓ No vendors allocated (skipping duplicate check)")

    # # Check 2: Proportional distribution balance (FTE_Avail / Forecast ratio)
    # if len(allocations_df) > 0:
    #     # Calculate ratio for each allocation
    #     allocations_df['Ratio'] = allocations_df['FTE Avail After'] / allocations_df['Forecast'].replace(0, 1)
    #     ratio_std = allocations_df['Ratio'].std()
    #     ratio_mean = allocations_df['Ratio'].mean()
    #     ratio_cv = (ratio_std / ratio_mean) * 100 if ratio_mean > 0 else 0  # Coefficient of variation

    #     # Good balance: CV < 20%
    #     balance_status = 'PASS' if ratio_cv < 20 else 'WARNING' if ratio_cv < 40 else 'FAIL'
    #     validation_data.append({
    #         'Check': 'Proportional Balance',
    #         'Status': balance_status,
    #         'Details': f'CV={ratio_cv:.1f}% (mean={ratio_mean:.3f}, std={ratio_std:.3f})'
    #     })
    #     logger.info(f"✓ FTE_Avail/Forecast ratio CV: {ratio_cv:.1f}% (lower is better, <20% is good)")
    # else:
    #     validation_data.append({
    #         'Check': 'Proportional Balance',
    #         'Status': 'N/A',
    #         'Details': 'No allocations to check'
    #     })

    # # Check 3: All vendors have valid state lists
    # if len(vendors_df) > 0 and 'Vendor States' in vendors_df.columns:
    #     vendors_with_empty_states = vendors_df[vendors_df['Vendor States'].isna() | (vendors_df['Vendor States'] == '')]
    #     validation_data.append({
    #         'Check': 'Valid Vendor States',
    #         'Status': 'PASS' if len(vendors_with_empty_states) == 0 else 'WARNING',
    #         'Details': f'{len(vendors_with_empty_states)} vendors with empty states' if len(vendors_with_empty_states) > 0 else 'All vendors have states'
    #     })
    # else:
    #     validation_data.append({
    #         'Check': 'Valid Vendor States',
    #         'Status': 'N/A',
    #         'Details': 'No vendors to check'
    #     })

    # validation_df = pd.DataFrame(validation_data)
    # logger.info(f"✓ Validation complete: {sum(validation_df['Status'] == 'PASS')}/{len(validation_df)} checks passed\n")

    # Create summary DataFrame
    summary_data = {
        'Metric': [
            'Month',
            'Year',
            'Total Bench Allocated',
            'Gaps Filled',
            'Excess Distributed',
            'Rows Modified',
            'Unique Forecast IDs',
            'Total Vendors Allocated'
        ],
        'Value': [
            result.month,
            result.year,
            result.total_bench_allocated,
            result.gaps_filled,
            result.excess_distributed,
            result.rows_modified,
            len(set([a.forecast_row.forecast_id for a in result.allocations])),
            len(vendors_data)
        ]
    }
    summary_df = pd.DataFrame(summary_data)

    # Export to Excel
    output_dir = os.path.join(os.getcwd(), 'code', 'logics')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    excel_path = os.path.join(output_dir, f'allocation_check_{month}_{year}_{timestamp}.xlsx')

    logger.info("Writing Excel file...")
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        # Summary sheet
        summary_df.to_excel(writer, sheet_name='Summary', index=False)

        # Allocations sheet
        allocations_df.to_excel(writer, sheet_name='Allocations', index=False)

        # Vendors sheet
        vendors_df.to_excel(writer, sheet_name='Vendors', index=False)

        # # Validation sheet
        # validation_df.to_excel(writer, sheet_name='Validation', index=False)

        # Format columns
        for sheet_name in writer.sheets:
            worksheet = writer.sheets[sheet_name]
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width

    logger.info(f"\n{'='*70}")
    logger.info(f"✓ ALLOCATION CHECK FILE CREATED")
    logger.info(f"{'='*70}")
    logger.info(f"Location: {excel_path}")
    logger.info(f"\nContents:")
    logger.info(f"  - Summary:     {len(summary_df)} metrics")
    logger.info(f"  - Allocations: {len(allocations_df)} allocation records")
    logger.info(f"  - Vendors:     {len(vendors_df)} vendor assignments")
    # logger.info(f"  - Validation:  {len(validation_df)} validation checks")
    logger.info(f"\nOpen this file to inspect the raw allocation result structure.")
    logger.info(f"{'='*70}\n")

    return excel_path


# ============================================================================
# FUNCTION 2: TEST FULL EXPORT
# ============================================================================

def test_full_export(month="March", year=2025):
    """
    Step 2: Test the complete export functionality with all 6 months data.

    This function:
    1. Runs bench allocation
    2. Fetches complete forecast records from database (all 6 months)
    3. Creates comprehensive 4-sheet workbook:
       - Modified Forecast Data (all 6 months, with allocated month updated)
       - Changes Detail (before/after comparison)
       - Vendor Assignments
       - Summary

    This does NOT update the database.

    Returns:
        str: Path to the created Excel file
    """
    logger.info(f"\n{'='*70}")
    logger.info(f"STEP 2: Testing full export for {month} {year}")
    logger.info(f"{'='*70}\n")

    # Initialize CoreUtils
    core_utils = CoreUtils(DATABASE_URL)

    # Run allocation logic
    logger.info("Running bench allocation...")
    result = allocate_bench_for_month(month, year, core_utils)

    if not result.success:
        logger.error(f"Allocation failed: {result.error}")
        return None

    logger.info("✓ Allocation completed successfully!")

    # Prepare data for export
    logger.info("\nFetching complete forecast records from database...")
    modified_rows = []
    changes_detail = []
    vendor_assignments = []

    # Track unique forecast IDs to avoid duplicates
    processed_forecast_ids = set()

    for alloc in result.allocations:
        row = alloc.forecast_row
        forecast_id = row.forecast_id

        # Only process each forecast_id once (avoid duplicate rows in Modified Forecast sheet)
        if forecast_id in processed_forecast_ids:
            # Still need to process changes_detail and vendor_assignments
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
            m_idx = row.month_index

            logger.info(f"  Processing forecast_id {forecast_id} - {complete_record['main_lob']} / {complete_record['state']} / {complete_record['case_type']}")

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
            modified_row[f'FTE Avail Month{m_idx}'] = row.fte_avail
            modified_row[f'Capacity Month{m_idx}'] = row.capacity

            modified_rows.append(modified_row)

        # Build changes detail (for all allocations, even duplicates)
        capacity_before = row.capacity_original
        capacity_change = alloc.capacity_change
        capacity_pct_change = (capacity_change / capacity_before) if capacity_before else 0

        change = {
            'main_lob': row.main_lob,
            'state': row.state,
            'case_type': row.case_type,
            'month': row.month_name,
            'fte_required': row.fte_required,
            'fte_avail_before': row.fte_avail_original,
            'fte_avail_after': row.fte_avail,
            'fte_change': alloc.fte_change,
            'allocation_type': f"Gap: {alloc.gap_fill_count}, Excess: {alloc.excess_distribution_count}",
            'vendors_allocated': len(alloc.vendors),
            'capacity_before': capacity_before,
            'capacity_after': row.capacity,
            'capacity_change': capacity_change,
            'capacity_pct_change': capacity_pct_change
        }
        changes_detail.append(change)

        # Vendor assignments
        for vendor in alloc.vendors:
            assignment = {
                'vendor_name': f"{vendor.first_name} {vendor.last_name}",
                'vendor_cn': vendor.cn,
                'vendor_skills': vendor.skills,
                'vendor_states': ", ".join(vendor.state_list),
                'allocated_to_lob': row.main_lob,
                'allocated_to_state': row.state,
                'allocated_to_worktype': row.case_type,
                'allocation_month': row.month_name,
                'allocation_type': "Bench"
            }
            vendor_assignments.append(assignment)

    # Convert to DataFrame
    modified_forecast_df = pd.DataFrame(modified_rows)

    # Create Summary Dict
    summary = {
        'month': month,
        'year': year,
        'total_bench_allocated': result.total_bench_allocated,
        'gaps_filled': result.gaps_filled,
        'excess_distributed': result.excess_distributed,
        'rows_modified': result.rows_modified,
        'validation': {'valid': True}
    }

    # Generate Export Excel using existing export logic
    logger.info("\nCreating comprehensive workbook...")
    output_dir = os.path.join(os.getcwd(), 'code', 'logics')
    excel_path = create_changes_workbook(
        changes=changes_detail,
        summary=summary,
        modified_forecast_rows=modified_forecast_df,
        vendor_assignments=vendor_assignments,
        output_dir=output_dir
    )

    logger.info(f"\n{'='*70}")
    logger.info(f"✓ FULL EXPORT FILE CREATED")
    logger.info(f"{'='*70}")
    logger.info(f"Location: {excel_path}")
    logger.info(f"\nContents:")
    logger.info(f"  - Summary:               Allocation statistics")
    logger.info(f"  - Modified Forecast:     {len(modified_forecast_df)} records (all 6 months)")
    logger.info(f"  - Changes Detail:        {len(changes_detail)} changes")
    logger.info(f"  - Vendor Assignments:    {len(vendor_assignments)} assignments")
    logger.info(f"\nNote: Modified Forecast sheet shows ALL 6 months with yellow/orange")
    logger.info(f"      highlighting on the allocated month's FTE Avail and Capacity.")
    logger.info(f"{'='*70}\n")

    return excel_path


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    """
    Main entry point for testing bench allocation.

    Uncomment the function you want to run:
    - check_allocation_result(): Quick check of raw allocation output
    - test_full_export(): Complete export with all 6 months data
    - Both: Run sequentially to see both outputs
    """

    # Configuration
    MONTH = "March"
    YEAR = 2025

    print("\n" + "="*70)
    print("BENCH ALLOCATION COMPREHENSIVE TESTING")
    print("="*70)
    print(f"Testing for: {MONTH} {YEAR}\n")

    # Option 1: Check raw allocation result first
    print("Running STEP 1: Allocation Result Check")
    check_file = check_allocation_result(month=MONTH, year=YEAR)

    # Option 2: Test full export
    # print("Running STEP 2: Full Export Test")
    # export_file = test_full_export(month=MONTH, year=YEAR)

    # Summary
    print("\n" + "="*70)
    print("TESTING COMPLETE!")
    print("="*70)
    if check_file:
        print(f"1. Allocation Check: {check_file}")
    # if export_file:
    #     print(f"2. Full Export:      {export_file}")
    print("="*70 + "\n")
