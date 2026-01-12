#!/usr/bin/env python3
"""
Type Consistency Verification Script

Verifies that migration column types match SQLModel field types.
Run this before deploying migrations to production.

Usage:
    python3 verify_type_consistency.py
"""

import sys
from typing import Dict, List, Tuple
from sqlalchemy import inspect, create_engine
from sqlmodel import SQLModel
from code.logics.db import (
    AllocationExecutionModel,
    MonthConfigurationModel,
    HistoryLogModel,
    HistoryChangeModel
)
from code.settings import SQLITE_DATABASE_URL, MSSQL_DATABASE_URL, MODE

def get_expected_types() -> Dict[str, Dict[str, str]]:
    """
    Define expected types for columns added/modified by migrations.

    Returns mapping: {table_name: {column_name: expected_type}}
    """
    return {
        'allocationexecutionmodel': {
            'BenchAllocationCompleted': 'BOOLEAN',  # SQLite: INTEGER, MSSQL: BIT
            'BenchAllocationCompletedAt': 'DATETIME',  # SQLite: TEXT, MSSQL: DATETIME
        },
        'monthconfigurationmodel': {
            'WorkHours': 'FLOAT',  # SQLite: REAL, MSSQL: FLOAT
        },
        'history_log': {
            'id': 'INTEGER',
            'history_log_id': 'VARCHAR',
            'Month': 'VARCHAR',
            'Year': 'INTEGER',
            'ChangeType': 'VARCHAR',
            'Timestamp': 'DATETIME',
            'User': 'VARCHAR',
            'Description': 'TEXT',
            'RecordsModified': 'INTEGER',
            'SummaryData': 'TEXT',
            'CreatedBy': 'VARCHAR',
            'CreatedDateTime': 'DATETIME',
        },
        'history_change': {
            'id': 'INTEGER',
            'history_log_id': 'VARCHAR',
            'MainLOB': 'VARCHAR',
            'State': 'VARCHAR',
            'CaseType': 'VARCHAR',
            'CaseID': 'VARCHAR',
            'FieldName': 'VARCHAR',
            'OldValue': 'TEXT',
            'NewValue': 'TEXT',
            'Delta': 'FLOAT',
            'MonthLabel': 'VARCHAR',
            'CreatedDateTime': 'DATETIME',
        }
    }

def normalize_type(db_type: str, is_sqlite: bool) -> str:
    """
    Normalize database-specific types to generic types for comparison.

    Args:
        db_type: Database-specific type (e.g., 'INTEGER', 'BIT', 'REAL')
        is_sqlite: True if SQLite, False if MSSQL

    Returns:
        Normalized type (e.g., 'BOOLEAN', 'FLOAT', 'VARCHAR')
    """
    db_type_upper = str(db_type).upper()

    # Boolean type normalization
    if is_sqlite:
        if 'INTEGER' in db_type_upper or 'BOOL' in db_type_upper:
            return 'BOOLEAN'  # SQLite uses INTEGER for bool
    else:
        if 'BIT' in db_type_upper or 'BOOL' in db_type_upper:
            return 'BOOLEAN'  # MSSQL uses BIT for bool

    # Float type normalization
    if is_sqlite:
        if 'REAL' in db_type_upper or 'FLOAT' in db_type_upper or 'DOUBLE' in db_type_upper:
            return 'FLOAT'
    else:
        if 'FLOAT' in db_type_upper or 'REAL' in db_type_upper or 'DOUBLE' in db_type_upper:
            return 'FLOAT'

    # Integer type normalization
    if 'INT' in db_type_upper:
        return 'INTEGER'

    # String type normalization
    if 'VARCHAR' in db_type_upper or 'CHAR' in db_type_upper or 'NVARCHAR' in db_type_upper:
        return 'VARCHAR'

    if 'TEXT' in db_type_upper or 'CLOB' in db_type_upper:
        return 'TEXT'

    # DateTime type normalization
    if 'DATETIME' in db_type_upper or 'TIMESTAMP' in db_type_upper:
        return 'DATETIME'
    if is_sqlite and 'TEXT' in db_type_upper:
        # SQLite stores datetime as TEXT
        return 'DATETIME'

    return db_type_upper

def verify_database_types(database_url: str, is_sqlite: bool) -> Tuple[bool, List[str]]:
    """
    Verify that database column types match expected types.

    Args:
        database_url: Database connection URL
        is_sqlite: True if SQLite, False if MSSQL

    Returns:
        Tuple of (all_passed: bool, errors: List[str])
    """
    print(f"\n{'='*60}")
    print(f"Verifying {'SQLite' if is_sqlite else 'MSSQL'} Database Types")
    print(f"{'='*60}\n")

    try:
        # Create engine and inspector
        engine = create_engine(database_url, echo=False)
        inspector = inspect(engine)

        expected_types = get_expected_types()
        errors = []
        passed = 0
        total = 0

        # Check each table
        for table_name, expected_columns in expected_types.items():
            # Check if table exists
            if table_name not in inspector.get_table_names():
                errors.append(f"❌ Table '{table_name}' does not exist")
                continue

            print(f"Checking table: {table_name}")

            # Get actual columns
            actual_columns = inspector.get_columns(table_name)
            actual_columns_dict = {col['name']: col for col in actual_columns}

            # Verify each expected column
            for col_name, expected_type in expected_columns.items():
                total += 1

                if col_name not in actual_columns_dict:
                    errors.append(f"  ❌ Column '{table_name}.{col_name}' does not exist")
                    continue

                actual_col = actual_columns_dict[col_name]
                actual_type_raw = str(actual_col['type'])
                actual_type_normalized = normalize_type(actual_type_raw, is_sqlite)

                # Special handling for BOOLEAN type
                if expected_type == 'BOOLEAN':
                    if is_sqlite:
                        # SQLite: Should be INTEGER
                        if actual_type_normalized == 'BOOLEAN' or 'INTEGER' in actual_type_raw.upper():
                            print(f"  ✅ {col_name}: {actual_type_raw} → BOOLEAN")
                            passed += 1
                        else:
                            errors.append(
                                f"  ❌ {col_name}: Expected BOOLEAN (INTEGER in SQLite), "
                                f"got {actual_type_raw}"
                            )
                    else:
                        # MSSQL: Should be BIT
                        if actual_type_normalized == 'BOOLEAN' or 'BIT' in actual_type_raw.upper():
                            print(f"  ✅ {col_name}: {actual_type_raw} → BOOLEAN")
                            passed += 1
                        else:
                            errors.append(
                                f"  ❌ {col_name}: Expected BOOLEAN (BIT in MSSQL), "
                                f"got {actual_type_raw}"
                            )

                elif actual_type_normalized == expected_type:
                    print(f"  ✅ {col_name}: {actual_type_raw} → {expected_type}")
                    passed += 1
                else:
                    errors.append(
                        f"  ❌ {col_name}: Expected {expected_type}, "
                        f"got {actual_type_raw} (normalized: {actual_type_normalized})"
                    )

        # Print summary
        print(f"\n{'='*60}")
        print(f"Summary: {passed}/{total} columns verified")
        print(f"{'='*60}\n")

        if errors:
            print("ERRORS FOUND:")
            for error in errors:
                print(error)
            return False, errors
        else:
            print("✅ All column types match expected types!")
            return True, []

    except Exception as e:
        error_msg = f"❌ Error connecting to database: {e}"
        print(error_msg)
        return False, [error_msg]

def main():
    """Main verification function."""
    print("\n" + "="*60)
    print("Database Type Consistency Verification")
    print("="*60)

    all_passed = True
    all_errors = []

    # Verify SQLite
    print(f"\nChecking SQLite database...")
    sqlite_passed, sqlite_errors = verify_database_types(SQLITE_DATABASE_URL, is_sqlite=True)
    if not sqlite_passed:
        all_passed = False
        all_errors.extend(sqlite_errors)

    # Verify MSSQL if in PRODUCTION mode
    if MODE.upper() == "PRODUCTION":
        print(f"\nChecking MSSQL database...")
        mssql_passed, mssql_errors = verify_database_types(MSSQL_DATABASE_URL, is_sqlite=False)
        if not mssql_passed:
            all_passed = False
            all_errors.extend(mssql_errors)
    else:
        print("\nℹ️  Skipping MSSQL verification (MODE is not PRODUCTION)")

    # Final summary
    print("\n" + "="*60)
    print("FINAL RESULT")
    print("="*60)

    if all_passed:
        print("✅ All type verifications PASSED!")
        print("✅ Safe to run migrations in production")
        return 0
    else:
        print(f"❌ {len(all_errors)} type verification errors found")
        print("❌ DO NOT run migrations in production until fixed")
        print("\nErrors:")
        for error in all_errors:
            print(error)
        return 1

if __name__ == "__main__":
    sys.exit(main())
