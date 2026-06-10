"""
Migration: Convert ForecastMonthsModel.Month1-6 from plain names to "Apr-2026" format.

Safe to re-run: skips rows already in the new format.
Rows whose UploadedFile name cannot be parsed (no month/year in filename) are skipped
with a warning — they will continue to work via the legacy backward-compat path.

Usage:
    python -m code.logics.migrations.migrate_forecast_month_codes
    python -m code.logics.migrations.migrate_forecast_month_codes --dry-run
"""

import argparse
import logging
import sys
from calendar import month_name as cal_month_name

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _compute_year_for_month(
    plain_month: str,
    upload_month: str,
    upload_year: int,
    first_month: str,
) -> int:
    """Replicate _compute_month_year_map logic for a single month."""
    month_names = list(cal_month_name)[1:]
    month_to_num = {m: i + 1 for i, m in enumerate(month_names)}

    upload_month_num = month_to_num.get(upload_month)
    first_month_num = month_to_num.get(first_month)
    m_num = month_to_num.get(plain_month)

    if not (upload_month_num and first_month_num and m_num):
        raise ValueError(
            f"Unknown month name: upload={upload_month!r}, "
            f"first={first_month!r}, target={plain_month!r}"
        )

    first_forecast_year = (
        upload_year if first_month_num > upload_month_num else upload_year + 1
    )
    return first_forecast_year if m_num >= first_month_num else first_forecast_year + 1


def run_migration(dry_run: bool = False) -> None:
    from code.logics.db import ForecastMonthsModel
    from code.logics.core_utils import PreProcessing
    from code.logics.month_code_utils import is_month_year_code, format_month_year_code
    from code.api.dependencies import get_core_utils

    core_utils = get_core_utils()
    db_manager = core_utils.get_db_manager(ForecastMonthsModel)
    pre = PreProcessing("forecast")

    updated = 0
    skipped_already_new = 0
    skipped_no_parse = 0

    with db_manager.SessionLocal() as session:
        records = session.query(ForecastMonthsModel).all()
        logger.info(f"Found {len(records)} ForecastMonthsModel rows")

        for record in records:
            # Check if already migrated (all months in new format)
            months_raw = [getattr(record, f"Month{i}") for i in range(1, 7)]
            if all(is_month_year_code(m) for m in months_raw if m):
                skipped_already_new += 1
                continue

            # Parse upload month/year from filename
            month_year = pre.get_month_year(record.UploadedFile or "")
            if not month_year:
                logger.warning(
                    f"  SKIP id={record.id} — cannot extract month/year from "
                    f"filename: {record.UploadedFile!r}"
                )
                skipped_no_parse += 1
                continue

            upload_month = month_year["Month"]
            upload_year = int(month_year["Year"])

            # Determine the plain months list; skip months already in new format
            plain_months = []
            for raw in months_raw:
                if is_month_year_code(raw):
                    # Partially migrated row — extract plain name for year map
                    from code.logics.month_code_utils import parse_month_year_code
                    plain, _ = parse_month_year_code(raw)
                    plain_months.append(plain)
                else:
                    plain_months.append(raw)

            first_month = plain_months[0] if plain_months else None
            if not first_month:
                logger.warning(f"  SKIP id={record.id} — Month1 is empty")
                skipped_no_parse += 1
                continue

            # Build new codes
            new_codes = []
            error = False
            for plain in plain_months:
                try:
                    year = _compute_year_for_month(plain, upload_month, upload_year, first_month)
                    new_codes.append(format_month_year_code(plain, year))
                except ValueError as e:
                    logger.warning(f"  SKIP id={record.id} — year calc error: {e}")
                    error = True
                    break

            if error:
                skipped_no_parse += 1
                continue

            old_display = ", ".join(months_raw)
            new_display = ", ".join(new_codes)
            logger.info(
                f"  {'[DRY-RUN] ' if dry_run else ''}id={record.id} "
                f"file={record.UploadedFile!r}\n"
                f"    OLD: {old_display}\n"
                f"    NEW: {new_display}"
            )

            if not dry_run:
                for i, code in enumerate(new_codes, start=1):
                    setattr(record, f"Month{i}", code)

            updated += 1

        if not dry_run and updated > 0:
            session.commit()
            logger.info(f"Committed {updated} updated rows")

    logger.info(
        f"\nDone — updated={updated}, "
        f"already_new={skipped_already_new}, "
        f"skipped_no_parse={skipped_no_parse}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Migrate ForecastMonthsModel month codes to 'Apr-2026' format"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print changes without writing to the database",
    )
    args = parser.parse_args()

    try:
        run_migration(dry_run=args.dry_run)
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)
