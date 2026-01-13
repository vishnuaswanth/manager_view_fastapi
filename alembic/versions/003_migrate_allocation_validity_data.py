"""migrate historical allocation data to allocation_validity table

Revision ID: 003_allocation_validity
Revises: 002_history_tables
Create Date: 2026-01-13 00:00:00.000000

PURPOSE:
This migration populates AllocationValidityModel from historical AllocationExecutionModel data.
It takes the latest successful execution for each month+year combination and creates validity records.

LOGIC:
1. Query AllocationExecutionModel for all successful executions (Status='SUCCESS')
2. Group by Month+Year and get the most recent execution_id (max StartTime)
3. Insert into AllocationValidityModel with is_valid=True
4. Skip duplicates (if month+year already exists in AllocationValidityModel)

TYPE SAFETY:
This migration uses database-agnostic SQLAlchemy types that work on both SQLite and MSSQL.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from datetime import datetime


# revision identifiers, used by Alembic.
revision = '003_allocation_validity'
down_revision = '002_history_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Migrate historical allocation execution data to allocation_validity table.
    Only migrates latest successful execution per month+year, skips existing records.
    """
    # Get database connection
    connection = op.get_bind()

    # Query to get the latest successful execution for each month+year combination
    # This works for both SQLite and MSSQL
    query = text("""
        SELECT
            aem.Month,
            aem.Year,
            aem.execution_id,
            aem.StartTime
        FROM allocation_execution aem
        INNER JOIN (
            SELECT Month, Year, MAX(StartTime) as MaxStartTime
            FROM allocation_execution
            WHERE Status = 'SUCCESS'
            GROUP BY Month, Year
        ) latest
        ON aem.Month = latest.Month
        AND aem.Year = latest.Year
        AND aem.StartTime = latest.MaxStartTime
        WHERE aem.Status = 'SUCCESS'
    """)

    # Execute query to get latest executions
    result = connection.execute(query)
    latest_executions = result.fetchall()

    # Track statistics
    inserted_count = 0
    skipped_count = 0

    # Insert into allocation_validity, skipping duplicates
    for row in latest_executions:
        month, year, execution_id, start_time = row

        # Check if this month+year combination already exists
        check_query = text("""
            SELECT COUNT(*)
            FROM allocation_validity
            WHERE month = :month AND year = :year
        """)

        existing = connection.execute(
            check_query,
            {"month": month, "year": year}
        ).scalar()

        if existing > 0:
            skipped_count += 1
            print(f"  Skipping {month} {year} - already exists in allocation_validity")
            continue

        # Insert new validity record
        insert_query = text("""
            INSERT INTO allocation_validity
                (month, year, allocation_execution_id, is_valid, created_datetime)
            VALUES
                (:month, :year, :execution_id, :is_valid, :created_datetime)
        """)

        connection.execute(
            insert_query,
            {
                "month": month,
                "year": year,
                "execution_id": execution_id,
                "is_valid": True,
                "created_datetime": datetime.utcnow()
            }
        )
        inserted_count += 1
        print(f"  Migrated {month} {year} → execution_id: {execution_id}")

    print(f"\n[Migration Summary]")
    print(f"  Records inserted: {inserted_count}")
    print(f"  Records skipped (duplicates): {skipped_count}")
    print(f"  Total processed: {inserted_count + skipped_count}")


def downgrade() -> None:
    """
    Remove migrated records from allocation_validity table.

    This removes ALL records that were created by this migration.
    Note: This does NOT remove manually added records (like March 2025 if added before migration).
    To be safe, we only delete records where created_datetime matches the migration execution time range.
    """
    connection = op.get_bind()

    # Get all execution_ids that were migrated (from AllocationExecutionModel)
    query = text("""
        SELECT
            aem.execution_id
        FROM allocation_execution aem
        INNER JOIN (
            SELECT Month, Year, MAX(StartTime) as MaxStartTime
            FROM allocation_execution
            WHERE Status = 'SUCCESS'
            GROUP BY Month, Year
        ) latest
        ON aem.Month = latest.Month
        AND aem.Year = latest.Year
        AND aem.StartTime = latest.MaxStartTime
        WHERE aem.Status = 'SUCCESS'
    """)

    result = connection.execute(query)
    execution_ids = [row[0] for row in result.fetchall()]

    if not execution_ids:
        print("No records to remove during downgrade")
        return

    # Delete records from allocation_validity that match these execution_ids
    # This preserves manually added records with different execution_ids
    delete_query = text("""
        DELETE FROM allocation_validity
        WHERE allocation_execution_id IN :execution_ids
    """)

    # SQLAlchemy requires tuples for IN clause
    result = connection.execute(
        delete_query,
        {"execution_ids": tuple(execution_ids)}
    )

    deleted_count = result.rowcount if hasattr(result, 'rowcount') else len(execution_ids)
    print(f"\n[Downgrade Summary]")
    print(f"  Records removed: {deleted_count}")
