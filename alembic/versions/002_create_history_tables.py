"""create history log and history change tables

Revision ID: 002_history_tables
Revises: 001_initial
Create Date: 2026-01-12 19:00:00.000000

TYPE SAFETY:
This migration uses database-agnostic SQLAlchemy types that work on both SQLite and MSSQL:
- sa.Integer() → INTEGER (SQLite) or INT (MSSQL)
- sa.String(N) → TEXT (SQLite) or VARCHAR(N) (MSSQL)
- sa.Text() → TEXT (SQLite) or VARCHAR(MAX) (MSSQL)
- sa.Float() → REAL (SQLite) or FLOAT (MSSQL)
- sa.DateTime() → TEXT (SQLite) or DATETIME (MSSQL)

Server defaults:
- sa.func.now() → CURRENT_TIMESTAMP (SQLite) or GETDATE() (MSSQL)

See TYPE_REFERENCE_QUICK.md for complete type mapping details.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import Index
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision = '002_history_tables'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def table_exists(table_name):
    """Check if a table exists."""
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """
    Create history_log and history_change tables for tracking forecast modifications.

    Compatible with both SQLite (development) and MSSQL (production).

    TRANSACTION SAFETY:
    - Uses Alembic's transaction context (auto-rollback on error)
    - Checks for existing tables before creating (idempotent)
    - All operations within this function are in a single transaction
    - If table creation fails, entire migration is rolled back

    Tables:
    - history_log: Tracks high-level change operations (bench allocation, CPH updates, etc.)
    - history_change: Tracks field-level changes for each history log entry
    """

    conn = op.get_bind()

    try:
        # ============================================================
        # TABLE 1: history_log
        # ============================================================

        if not table_exists('history_log'):
            print("✓ Creating history_log table...")
            op.create_table(
                'history_log',
                # Primary Key
                sa.Column('id', sa.Integer(), nullable=False, primary_key=True),

                # Unique Identifier (UUID for linking)
                sa.Column('history_log_id', sa.String(36), nullable=False, unique=True),

                # Time Period
                sa.Column('Month', sa.String(15), nullable=False),
                sa.Column('Year', sa.Integer(), nullable=False),

                # Change Metadata
                sa.Column('ChangeType', sa.String(50), nullable=False),
                sa.Column('Timestamp', sa.DateTime(), nullable=False, server_default=sa.func.now()),
                sa.Column('User', sa.String(100), nullable=False),
                sa.Column('Description', sa.Text(), nullable=True),

                # Statistics
                sa.Column('RecordsModified', sa.Integer(), nullable=False),
                sa.Column('SummaryData', sa.Text(), nullable=True),

                # Audit Trail
                sa.Column('CreatedBy', sa.String(100), nullable=False),
                sa.Column('CreatedDateTime', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            )

            # Create indexes for history_log
            op.create_index('idx_history_month_year', 'history_log', ['Month', 'Year', 'Timestamp'])
            op.create_index('idx_history_change_type', 'history_log', ['ChangeType', 'Timestamp'])
            op.create_index('idx_history_user', 'history_log', ['User', 'Timestamp'])
            op.create_index('idx_history_log_id', 'history_log', ['history_log_id'])

            print("→ history_log table created")
        else:
            print("→ history_log table already exists, skipping...")

        # ============================================================
        # TABLE 2: history_change
        # ============================================================

        if not table_exists('history_change'):
            print("✓ Creating history_change table...")
            op.create_table(
            'history_change',
            # Primary Key
            sa.Column('id', sa.Integer(), nullable=False, primary_key=True),

            # Link to parent (string-based, no ForeignKey constraint for flexibility)
            sa.Column('history_log_id', sa.String(36), nullable=False),

            # Record Identifiers (composite key for forecast row)
            sa.Column('MainLOB', sa.String(255), nullable=False),
            sa.Column('State', sa.String(100), nullable=False),
            sa.Column('CaseType', sa.String(255), nullable=False),
            sa.Column('CaseID', sa.String(100), nullable=False),

            # Field Change Details
            sa.Column('FieldName', sa.String(100), nullable=False),
            sa.Column('OldValue', sa.Text(), nullable=True),
            sa.Column('NewValue', sa.Text(), nullable=True),
            sa.Column('Delta', sa.Float(), nullable=True),

            # Month Context
            sa.Column('MonthLabel', sa.String(15), nullable=True),

            # Audit Trail
            sa.Column('CreatedDateTime', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

        # Create indexes for history_change
        op.create_index('idx_change_history_log', 'history_change', ['history_log_id'])
        op.create_index('idx_change_identifiers', 'history_change', ['MainLOB', 'State', 'CaseType', 'CaseID'])
        op.create_index('idx_change_field', 'history_change', ['FieldName'])
        op.create_index('idx_change_month', 'history_change', ['MonthLabel'])

            print("✓ history_change table created")
        else:
            print("→ history_change table already exists, skipping...")

        print("\n✅ Migration 002 completed successfully!")

    except Exception as e:
        print(f"\n❌ ERROR during migration: {e}")
        print("⚠️  Transaction will be rolled back automatically by Alembic")
        raise  # Re-raise to trigger Alembic's automatic rollback


def downgrade() -> None:
    """
    Drop history_log and history_change tables.

    WARNING: This will delete all history tracking data!

    TRANSACTION SAFETY:
    - All operations within this function are in a single transaction
    - Automatic rollback on error
    """

    conn = op.get_bind()

    try:
        # Drop in reverse order (child table first)
        if table_exists('history_change'):
            print("✓ Dropping history_change table...")
            op.drop_table('history_change')
            print("→ history_change table dropped")
        else:
            print("→ history_change table doesn't exist, skipping...")

        if table_exists('history_log'):
            print("✓ Dropping history_log table...")
            op.drop_table('history_log')
            print("→ history_log table dropped")
        else:
            print("→ history_log table doesn't exist, skipping...")

        print("\n✅ Migration 002 downgrade completed successfully!")

    except Exception as e:
        print(f"\n❌ ERROR during downgrade: {e}")
        print("⚠️  Transaction will be rolled back automatically by Alembic")
        raise  # Re-raise to trigger Alembic's automatic rollback
