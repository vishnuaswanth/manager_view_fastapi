#!/usr/bin/env python3
"""
Import target_cph.xlsx data into TargetCPHModel table.

This script reads Target CPH data from an Excel file and imports it into the database
using the bulk_add_target_cph_configurations() function.

Usage:
    python scripts/import_target_cph.py [--file path/to/excel] [--created-by username]

Arguments:
    --file        Path to the Excel file (default: target_cph.xlsx in project root)
    --created-by  Username for audit trail (default: "system")
    --dry-run     Preview changes without importing

Examples:
    # Import from default file with default user
    python scripts/import_target_cph.py

    # Import from specific file
    python scripts/import_target_cph.py --file /path/to/target_cph.xlsx

    # Import with specific user
    python scripts/import_target_cph.py --created-by admin

    # Preview without importing
    python scripts/import_target_cph.py --dry-run
"""

import argparse
import sys
import os

# Add the project root to the path so we can import from code.*
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import pandas as pd
from typing import List, Dict


def load_excel_data(file_path: str) -> List[Dict]:
    """
    Load Target CPH data from Excel file.

    Expected columns: 'Main LOB', 'Case type', 'Target CPH'

    Args:
        file_path: Path to the Excel file

    Returns:
        List of configuration dictionaries

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If required columns are missing
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    # Read Excel file
    df = pd.read_excel(file_path)

    # Validate required columns
    required_columns = ['Main LOB', 'Case type', 'Target CPH']
    missing_columns = [col for col in required_columns if col not in df.columns]

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}. "
            f"Found columns: {list(df.columns)}"
        )

    # Convert to list of dicts
    configs = []
    for idx, row in df.iterrows():
        main_lob = str(row['Main LOB']).strip()
        case_type = str(row['Case type']).strip()
        target_cph = float(row['Target CPH'])

        # Skip empty rows
        if not main_lob or main_lob == 'nan' or not case_type or case_type == 'nan':
            print(f"  Skipping row {idx + 2}: Empty Main LOB or Case type")
            continue

        configs.append({
            'main_lob': main_lob,
            'case_type': case_type,
            'target_cph': target_cph
        })

    return configs


def import_target_cph(
    file_path: str,
    created_by: str = "system",
    dry_run: bool = False
) -> Dict:
    """
    Import Target CPH data from Excel file into database.

    Args:
        file_path: Path to the Excel file
        created_by: Username for audit trail
        dry_run: If True, only preview without importing

    Returns:
        Dictionary with import results
    """
    print(f"\n{'='*60}")
    print(f"Target CPH Import Script")
    print(f"{'='*60}")
    print(f"File: {file_path}")
    print(f"Created by: {created_by}")
    print(f"Dry run: {dry_run}")
    print(f"{'='*60}\n")

    # Load data from Excel
    print("Loading data from Excel...")
    configs = load_excel_data(file_path)
    print(f"Found {len(configs)} valid configurations\n")

    if not configs:
        print("No configurations to import.")
        return {'total': 0, 'succeeded': 0, 'failed': 0}

    # Preview data
    print("Preview of first 5 configurations:")
    print("-" * 80)
    for i, config in enumerate(configs[:5]):
        print(f"  {i+1}. {config['main_lob'][:40]:<40} | {config['case_type'][:25]:<25} | CPH: {config['target_cph']}")
    if len(configs) > 5:
        print(f"  ... and {len(configs) - 5} more")
    print("-" * 80)
    print()

    if dry_run:
        print("DRY RUN - No data was imported.")
        return {
            'total': len(configs),
            'succeeded': 0,
            'failed': 0,
            'dry_run': True
        }

    # Import data
    print("Importing data into database...")
    from code.logics.target_cph_utils import bulk_add_target_cph_configurations

    # Add created_by to each config
    for config in configs:
        config['created_by'] = created_by

    result = bulk_add_target_cph_configurations(configurations=configs)

    # Print results
    print(f"\n{'='*60}")
    print("Import Results:")
    print(f"{'='*60}")
    print(f"  Total attempted: {result['total']}")
    print(f"  Succeeded: {result['succeeded']}")
    print(f"  Failed: {result['failed']}")
    print(f"  Duplicates skipped: {result.get('duplicates_skipped', 0)}")

    if result.get('errors'):
        print(f"\nErrors:")
        for error in result['errors'][:10]:
            print(f"  - {error}")
        if len(result['errors']) > 10:
            print(f"  ... and {len(result['errors']) - 10} more errors")

    print(f"{'='*60}\n")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Import Target CPH data from Excel file into database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--file',
        type=str,
        default=os.path.join(project_root, 'target_cph.xlsx'),
        help='Path to the Excel file (default: target_cph.xlsx in project root)'
    )
    parser.add_argument(
        '--created-by',
        type=str,
        default='system',
        help='Username for audit trail (default: system)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without importing'
    )

    args = parser.parse_args()

    try:
        result = import_target_cph(
            file_path=args.file,
            created_by=args.created_by,
            dry_run=args.dry_run
        )

        # Exit with appropriate code
        if result.get('failed', 0) > 0 and result.get('succeeded', 0) == 0:
            sys.exit(1)
        else:
            sys.exit(0)

    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
