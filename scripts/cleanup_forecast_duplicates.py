#!/usr/bin/env python3
"""
Clean up duplicate ForecastModel rows.

Historically, the forecast upload flow could create duplicate ForecastModel rows for
the same (Month, Year, Main_LOB, State, Case_Type) combination — it writes to
ForecastModel twice per upload (a synchronous demand pre-population insert, then an
async background allocation task's final insert), and overlapping runs for the same
month could race on the delete-then-insert `replace=True` logic in save_to_db,
leaving both runs' rows behind. That race is now guarded against in upload_router.py.
This script removes rows left over from before that guard existed.

For each duplicate group, the row with the highest `id` is kept (this matches the
dedup logic already used by get_reallocation_data/calculate_reallocation_preview in
forecast_reallocation_transformer.py, so this script keeps the same row those
endpoints already treat as canonical).

RampModel.forecast_id references ForecastModel.id directly (no DB-level FK), so
before deleting a losing duplicate this script re-points any RampModel rows that
reference it to the surviving row — unless the surviving row already has a ramp row
for the same (month_key, ramp_name), in which case the whole group is left untouched
and flagged for manual review.

Usage:
    python scripts/cleanup_forecast_duplicates.py --dry-run
    python scripts/cleanup_forecast_duplicates.py --dry-run --month April --year 2025
    python scripts/cleanup_forecast_duplicates.py --execute --month April --year 2025

Arguments:
    --dry-run     Report duplicates/conflicts without writing anything (default)
    --execute     Actually re-point ramp rows and delete losing duplicates
    --month       Optional: scope to a single report month (e.g. "April")
    --year        Optional: scope to a single report year (e.g. 2025)
"""

import argparse
import os
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

# Add the project root to the path so we can import from code.*
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from code.logics.core_utils import CoreUtils
from code.logics.db import ForecastModel, RampModel
from code.settings import MODE, SQLITE_DATABASE_URL, MSSQL_DATABASE_URL

if MODE.upper() == "DEBUG":
    DATABASE_URL = SQLITE_DATABASE_URL
elif MODE.upper() == "PRODUCTION":
    DATABASE_URL = MSSQL_DATABASE_URL
else:
    raise ValueError("Invalid MODE specified in config.")

core_utils = CoreUtils(DATABASE_URL)

GroupKey = Tuple[str, int, str, str, str]  # Month, Year, Main_LOB, State, Case_Type


def business_key(record: ForecastModel) -> GroupKey:
    return (
        record.Month,
        record.Year,
        record.Centene_Capacity_Plan_Main_LOB,
        record.Centene_Capacity_Plan_State,
        record.Centene_Capacity_Plan_Case_Type,
    )


def find_duplicate_groups(
    session, month: Optional[str], year: Optional[int]
) -> Dict[GroupKey, List[ForecastModel]]:
    query = session.query(ForecastModel)
    if month:
        query = query.filter(ForecastModel.Month == month)
    if year:
        query = query.filter(ForecastModel.Year == year)

    groups: Dict[GroupKey, List[ForecastModel]] = defaultdict(list)
    for record in query.order_by(ForecastModel.id.asc()).all():
        groups[business_key(record)].append(record)

    return {key: records for key, records in groups.items() if len(records) > 1}


def plan_group_cleanup(session, winner: ForecastModel, losers: List[ForecastModel]):
    """
    Determine the ramp re-point + delete plan for one duplicate group.

    Returns a dict describing the plan, or None if the group has a ramp conflict
    and must be skipped.
    """
    winner_ramps = session.query(RampModel).filter(
        RampModel.forecast_id == winner.id
    ).all()
    winner_ramp_keys = {(r.month_key, r.ramp_name) for r in winner_ramps}

    repoint_ramp_ids: List[int] = []
    delete_forecast_ids: List[int] = []

    for loser in losers:
        loser_ramps = session.query(RampModel).filter(
            RampModel.forecast_id == loser.id
        ).all()

        if not loser_ramps:
            delete_forecast_ids.append(loser.id)
            continue

        loser_ramp_keys = {(r.month_key, r.ramp_name) for r in loser_ramps}
        if loser_ramp_keys & winner_ramp_keys:
            return None  # conflict — leave the whole group untouched

        repoint_ramp_ids.extend(r.id for r in loser_ramps)
        delete_forecast_ids.append(loser.id)
        # Track this loser's ramp keys so a later loser in the same group can't
        # collide with rows we're about to re-point onto the winner either.
        winner_ramp_keys |= loser_ramp_keys

    return {
        "repoint_ramp_ids": repoint_ramp_ids,
        "delete_forecast_ids": delete_forecast_ids,
    }


def build_report(session, groups: Dict[GroupKey, List[ForecastModel]]):
    plans = {}
    conflicts = []

    for key, records in groups.items():
        winner = max(records, key=lambda r: r.id)
        losers = [r for r in records if r.id != winner.id]

        plan = plan_group_cleanup(session, winner, losers)
        if plan is None:
            conflicts.append((key, [r.id for r in records]))
        else:
            plans[key] = plan

    return plans, conflicts


def print_report(groups, plans, conflicts):
    total_delete = sum(len(p["delete_forecast_ids"]) for p in plans.values())
    total_repoint = sum(len(p["repoint_ramp_ids"]) for p in plans.values())

    print(f"Duplicate groups found: {len(groups)}")
    print(f"  Resolvable groups:    {len(plans)}  ({total_delete} rows to delete, {total_repoint} ramp rows to re-point)")
    print(f"  Conflicting groups:   {len(conflicts)}  (left untouched, need manual review)")

    if conflicts:
        print("\nConflicting groups (ramp data overlaps on (month_key, ramp_name) — not auto-resolved):")
        for (month, year, lob, state, case_type), ids in conflicts:
            print(f"  - {month} {year} | {lob} | {state} | {case_type} | ForecastModel ids: {ids}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--execute", action="store_true", help="Actually perform the cleanup (default is dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no writes (default behavior)")
    parser.add_argument("--month", type=str, default=None, help="Scope to a single report month, e.g. 'April'")
    parser.add_argument("--year", type=int, default=None, help="Scope to a single report year, e.g. 2025")
    args = parser.parse_args()

    execute = args.execute and not args.dry_run

    db_manager = core_utils.get_db_manager(ForecastModel)
    with db_manager.SessionLocal() as session:
        groups = find_duplicate_groups(session, args.month, args.year)
        if not groups:
            print("No duplicate ForecastModel rows found.")
            return

        plans, conflicts = build_report(session, groups)
        print_report(groups, plans, conflicts)

        if not execute:
            print("\nDry run only — no changes made. Re-run with --execute to apply.")
            return

        confirm = input(
            f"\nAbout to delete {sum(len(p['delete_forecast_ids']) for p in plans.values())} "
            f"ForecastModel rows against database mode '{MODE}'. "
            "Make sure you have a backup. Type 'yes' to continue: "
        )
        if confirm.strip().lower() != "yes":
            print("Aborted — no changes made.")
            return

        try:
            for key, records in groups.items():
                if key not in plans:
                    continue
                winner = max(records, key=lambda r: r.id)
                plan = plans[key]
                if plan["repoint_ramp_ids"]:
                    session.query(RampModel).filter(
                        RampModel.id.in_(plan["repoint_ramp_ids"])
                    ).update({RampModel.forecast_id: winner.id}, synchronize_session=False)
                if plan["delete_forecast_ids"]:
                    session.query(ForecastModel).filter(
                        ForecastModel.id.in_(plan["delete_forecast_ids"])
                    ).delete(synchronize_session=False)

            session.commit()
            print(f"\nDone. Deleted duplicates in {len(plans)} groups. {len(conflicts)} groups skipped (conflicts).")
        except Exception as e:
            session.rollback()
            print(f"\nError during cleanup, rolled back: {e}")
            raise


if __name__ == "__main__":
    main()
