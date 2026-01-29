"""create fte_allocation_mapping table for LLM queries

Revision ID: 004_fte_allocation_mapping
Revises: 003_allocation_validity
Create Date: 2026-01-29 00:00:00.000000

PURPOSE:
This migration creates the fte_allocation_mapping table which stores denormalized
FTE-to-forecast mappings for fast LLM querying.

The table enables querying which FTEs (resources) are allocated to specific
forecast records without parsing JSON blobs from roster_allotment reports.

TYPE SAFETY:
This migration uses database-agnostic SQLAlchemy types that work on both SQLite and MSSQL:
- sa.Integer() → INTEGER (SQLite) or INT (MSSQL)
- sa.String(N) → TEXT (SQLite) or VARCHAR(N) (MSSQL)
- sa.DateTime() → TEXT (SQLite) or DATETIME (MSSQL)

Server defaults:
- sa.func.now() → CURRENT_TIMESTAMP (SQLite) or GETDATE() (MSSQL)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision = '004_fte_allocation_mapping'
down_revision = '003_allocation_validity'
branch_labels = None
depends_on = None


def table_exists(table_name):
    """Check if a table exists."""
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """
    Create fte_allocation_mapping table for storing FTE-to-forecast mappings.

    Compatible with both SQLite (development) and MSSQL (production).

    TRANSACTION SAFETY:
    - Uses Alembic's transaction context (auto-rollback on error)
    - Checks for existing table before creating (idempotent)
    - All operations within this function are in a single transaction
    """

    try:
        if not table_exists('fte_allocation_mapping'):
            print("✓ Creating fte_allocation_mapping table...")
            op.create_table(
                'fte_allocation_mapping',
                # Primary Key
                sa.Column('id', sa.Integer(), nullable=False, primary_key=True),

                # Execution/Validity tracking
                sa.Column('allocation_execution_id', sa.String(36), nullable=False),
                sa.Column('report_month', sa.String(15), nullable=False),
                sa.Column('report_year', sa.Integer(), nullable=False),

                # Forecast record identification
                sa.Column('main_lob', sa.String(255), nullable=False),
                sa.Column('state', sa.String(100), nullable=False),
                sa.Column('case_type', sa.String(255), nullable=False),
                sa.Column('call_type_id', sa.String(100), nullable=True),

                # Forecast month context
                sa.Column('forecast_month', sa.String(15), nullable=False),
                sa.Column('forecast_year', sa.Integer(), nullable=False),
                sa.Column('forecast_month_label', sa.String(10), nullable=False),
                sa.Column('forecast_month_index', sa.Integer(), nullable=False),

                # FTE/Resource details (denormalized from roster)
                sa.Column('cn', sa.String(50), nullable=False),
                sa.Column('first_name', sa.String(100), nullable=True),
                sa.Column('last_name', sa.String(100), nullable=True),
                sa.Column('opid', sa.String(50), nullable=True),
                sa.Column('primary_platform', sa.String(100), nullable=True),
                sa.Column('primary_market', sa.String(100), nullable=True),
                sa.Column('location', sa.String(100), nullable=True),
                sa.Column('original_state', sa.String(100), nullable=True),
                sa.Column('worktype', sa.String(255), nullable=True),

                # Allocation source
                sa.Column('allocation_type', sa.String(20), nullable=False),

                # Audit trail
                sa.Column('created_datetime', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            )

            # Create indexes for query performance
            print("✓ Creating indexes...")

            # Primary query pattern: (report_month, report_year, main_lob, state, case_type)
            op.create_index(
                'idx_fte_mapping_query',
                'fte_allocation_mapping',
                ['report_month', 'report_year', 'main_lob', 'state', 'case_type']
            )

            # Forecast month filtering
            op.create_index(
                'idx_fte_mapping_forecast_month',
                'fte_allocation_mapping',
                ['report_month', 'report_year', 'forecast_month_label']
            )

            # LOB/State/Case type lookup
            op.create_index(
                'idx_fte_mapping_lob_state_case',
                'fte_allocation_mapping',
                ['main_lob', 'state', 'case_type']
            )

            # CN lookup for reverse queries
            op.create_index(
                'idx_fte_mapping_cn',
                'fte_allocation_mapping',
                ['cn']
            )

            # Execution ID for cleanup
            op.create_index(
                'idx_fte_mapping_execution',
                'fte_allocation_mapping',
                ['allocation_execution_id']
            )

            print("→ fte_allocation_mapping table created with indexes")
        else:
            print("→ fte_allocation_mapping table already exists, skipping...")

        print("\n✅ Migration 004 completed successfully!")

    except Exception as e:
        print(f"\n❌ ERROR during migration: {e}")
        print("⚠️  Transaction will be rolled back automatically by Alembic")
        raise


def downgrade() -> None:
    """
    Drop fte_allocation_mapping table.

    WARNING: This will delete all FTE allocation mapping data!

    TRANSACTION SAFETY:
    - All operations within this function are in a single transaction
    - Automatic rollback on error
    """

    try:
        if table_exists('fte_allocation_mapping'):
            print("✓ Dropping fte_allocation_mapping table...")
            op.drop_table('fte_allocation_mapping')
            print("→ fte_allocation_mapping table dropped")
        else:
            print("→ fte_allocation_mapping table doesn't exist, skipping...")

        print("\n✅ Migration 004 downgrade completed successfully!")

    except Exception as e:
        print(f"\n❌ ERROR during downgrade: {e}")
        print("⚠️  Transaction will be rolled back automatically by Alembic")
        raise
