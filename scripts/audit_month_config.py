#!/usr/bin/env python3
"""
Audit MonthConfigurationModel rows for data inconsistencies.

Two independent consumers of this table do exact-match lookups: the Configuration
view's month filter (Django, client-side string equality against the canonical full
month name) and the allocation engine's Calculations.get_config_for_worktype()
(manager_view_fastapi/code/logics/allocation.py), which raises "CRITICAL: No month
configuration found for <month> <year>" when the lookup misses. Both fail silently
against rows whose Month/WorkType/Year don't match the canonical form, even though
those rows are visible in an unfiltered list - which is exactly the "Feb 2026 shows
up unfiltered but not when filtered, and allocation says it's missing" symptom this
script was written to track down.

All write paths (add_month_configuration, bulk_add_month_configurations) now reject
malformed Month/WorkType/Year values at insert time (see month_config_utils.py), but
that doesn't retroactively fix rows written before that check existed, or rows
written by some other path (a script, a direct DB edit, etc.). This script finds
those rows.

This script is READ-ONLY - it does not modify any data. Review its report and fix
flagged rows deliberately (e.g. via the FastAPI update endpoint, or a one-off SQL
UPDATE for the specific bad value), since duplicates in particular may need a human
decision about which row is correct rather than a blind rewrite.

Checks performed, per row:
    - Month is an exact, case-sensitive match against one of the 12 canonical full
      month names (e.g. "February", not "Feb", "february", or "February " with
      trailing whitespace).
    - WorkType is exactly "Domestic" or "Global".
    - Year is within the sane bounds enforced at insert time (2020-2100).
    - String fields have no leading/trailing whitespace.
Checks performed, per (Month, Year) group:
    - Exactly one Domestic and one Global row exist (no missing pair, no duplicates).

Usage:
    python scripts/audit_month_config.py
    python scripts/audit_month_config.py --month February --year 2026
"""

import argparse
import os
import sys
from collections import defaultdict

# Add the project root to the path so we can import from code.*
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from code.logics.core_utils import CoreUtils
from code.logics.db import MonthConfigurationModel
from code.settings import MODE, SQLITE_DATABASE_URL, MSSQL_DATABASE_URL
from code.logics.month_config_utils import (
    VALID_MONTH_NAMES,
    VALID_WORK_TYPES,
    MIN_CONFIG_YEAR,
    MAX_CONFIG_YEAR,
)

if MODE.upper() == "DEBUG":
    DATABASE_URL = SQLITE_DATABASE_URL
elif MODE.upper() == "PRODUCTION":
    DATABASE_URL = MSSQL_DATABASE_URL
else:
    raise ValueError("Invalid MODE specified in config.")

core_utils = CoreUtils(DATABASE_URL)


def audit_row(record: MonthConfigurationModel):
    """Return a list of problem strings for a single row, empty if clean."""
    problems = []

    month_raw = record.Month
    month_str = str(month_raw) if month_raw is not None else ""

    if month_str != month_str.strip():
        problems.append(f"Month has leading/trailing whitespace: {month_raw!r}")

    if month_str.strip() not in VALID_MONTH_NAMES:
        problems.append(
            f"Month is not a canonical full month name: {month_raw!r} "
            f"(expected one of {sorted(VALID_MONTH_NAMES)})"
        )

    work_type_raw = record.WorkType
    work_type_str = str(work_type_raw) if work_type_raw is not None else ""

    if work_type_str != work_type_str.strip():
        problems.append(f"WorkType has leading/trailing whitespace: {work_type_raw!r}")

    if work_type_str.strip() not in VALID_WORK_TYPES:
        problems.append(
            f"WorkType is not 'Domestic'/'Global': {work_type_raw!r}"
        )

    if record.Year is None or not (MIN_CONFIG_YEAR <= record.Year <= MAX_CONFIG_YEAR):
        problems.append(
            f"Year is out of bounds ({MIN_CONFIG_YEAR}-{MAX_CONFIG_YEAR}): {record.Year!r}"
        )

    return problems


def audit_pairs(records):
    """
    Group by (Month, Year) exactly as stored (not normalized) so a corrupted Month
    value shows up as its own group rather than being silently folded into the
    correct one. Returns a list of (month, year, work_types, record_ids) for any
    group that isn't exactly one Domestic + one Global.
    """
    groups = defaultdict(list)
    for record in records:
        groups[(record.Month, record.Year)].append(record)

    problems = []
    for (month, year), group_records in groups.items():
        work_types = [r.WorkType for r in group_records]
        ids = [r.id for r in group_records]
        if sorted(work_types) != ["Domestic", "Global"]:
            problems.append((month, year, work_types, ids))

    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--month", type=str, default=None, help="Scope to a single Month value as stored, e.g. 'February'")
    parser.add_argument("--year", type=int, default=None, help="Scope to a single year, e.g. 2026")
    args = parser.parse_args()

    db_manager = core_utils.get_db_manager(MonthConfigurationModel)
    with db_manager.SessionLocal() as session:
        query = session.query(MonthConfigurationModel)
        if args.month:
            query = query.filter(MonthConfigurationModel.Month == args.month)
        if args.year:
            query = query.filter(MonthConfigurationModel.Year == args.year)

        records = query.order_by(
            MonthConfigurationModel.Year, MonthConfigurationModel.Month, MonthConfigurationModel.WorkType
        ).all()

    if not records:
        print("No MonthConfigurationModel rows found for the given scope.")
        return

    print(f"Scanned {len(records)} row(s).\n")

    row_problem_count = 0
    for record in records:
        problems = audit_row(record)
        if problems:
            row_problem_count += 1
            print(f"[Row id={record.id}] Month={record.Month!r} Year={record.Year!r} WorkType={record.WorkType!r}")
            for p in problems:
                print(f"    - {p}")

    pair_problems = audit_pairs(records)

    if row_problem_count == 0:
        print("No per-row field inconsistencies found.")
    else:
        print(f"\n{row_problem_count} row(s) with field inconsistencies.")

    if pair_problems:
        print(f"\n{len(pair_problems)} (Month, Year) group(s) not properly paired (need exactly one Domestic + one Global):")
        for month, year, work_types, ids in pair_problems:
            print(f"    - Month={month!r} Year={year!r}: work_types={work_types} row ids={ids}")
    else:
        print("\nAll (Month, Year) groups are properly paired.")

    print("\nThis script made no changes. Review the rows above and fix deliberately.")


if __name__ == "__main__":
    main()
