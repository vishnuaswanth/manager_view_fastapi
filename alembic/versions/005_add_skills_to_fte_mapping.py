"""add new_work_type and skills columns to fte_allocation_mapping

Revision ID: 005_add_skills_to_fte_mapping
Revises: 004_fte_allocation_mapping
Create Date: 2026-01-30 00:00:00.000000

PURPOSE:
This migration adds two new columns to the fte_allocation_mapping table:
- new_work_type: Raw NewWorkType value from ProdTeamRosterModel
- skills: Comma-separated parsed skills (using vocabulary-based parsing)

These columns enable LLM queries to access vendor skills information directly
without needing to parse the NewWorkType field.

TYPE SAFETY:
This migration uses database-agnostic SQLAlchemy types that work on both SQLite and MSSQL:
- sa.String(N) -> TEXT (SQLite) or VARCHAR(N) (MSSQL)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision = '005_add_skills_to_fte_mapping'
down_revision = '004_fte_allocation_mapping'
branch_labels = None
depends_on = None


def table_exists(table_name):
    """Check if a table exists."""
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    return table_name in inspector.get_table_names()


def column_exists(table_name, column_name):
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    """
    Add new_work_type and skills columns to fte_allocation_mapping table.

    Compatible with both SQLite (development) and MSSQL (production).

    TRANSACTION SAFETY:
    - Uses Alembic's transaction context (auto-rollback on error)
    - Checks for existing columns before adding (idempotent)
    - All operations within this function are in a single transaction
    """

    try:
        if not table_exists('fte_allocation_mapping'):
            print("! fte_allocation_mapping table does not exist, skipping...")
            print("  Run migration 004 first to create the table.")
            return

        # Add new_work_type column
        if not column_exists('fte_allocation_mapping', 'new_work_type'):
            print("+ Adding new_work_type column...")
            op.add_column(
                'fte_allocation_mapping',
                sa.Column('new_work_type', sa.String(500), nullable=True)
            )
            print("  new_work_type column added")
        else:
            print("- new_work_type column already exists, skipping...")

        # Add skills column
        if not column_exists('fte_allocation_mapping', 'skills'):
            print("+ Adding skills column...")
            op.add_column(
                'fte_allocation_mapping',
                sa.Column('skills', sa.String(500), nullable=True)
            )
            print("  skills column added")
        else:
            print("- skills column already exists, skipping...")

        print("\n Migration 005 completed successfully!")

    except Exception as e:
        print(f"\n ERROR during migration: {e}")
        print("  Transaction will be rolled back automatically by Alembic")
        raise


def downgrade() -> None:
    """
    Remove new_work_type and skills columns from fte_allocation_mapping table.

    WARNING: This will delete all data in these columns!

    TRANSACTION SAFETY:
    - All operations within this function are in a single transaction
    - Automatic rollback on error
    """

    try:
        if not table_exists('fte_allocation_mapping'):
            print("- fte_allocation_mapping table does not exist, skipping...")
            return

        # Remove skills column
        if column_exists('fte_allocation_mapping', 'skills'):
            print("- Dropping skills column...")
            op.drop_column('fte_allocation_mapping', 'skills')
            print("  skills column dropped")
        else:
            print("- skills column does not exist, skipping...")

        # Remove new_work_type column
        if column_exists('fte_allocation_mapping', 'new_work_type'):
            print("- Dropping new_work_type column...")
            op.drop_column('fte_allocation_mapping', 'new_work_type')
            print("  new_work_type column dropped")
        else:
            print("- new_work_type column does not exist, skipping...")

        print("\n Migration 005 downgrade completed successfully!")

    except Exception as e:
        print(f"\n ERROR during downgrade: {e}")
        print("  Transaction will be rolled back automatically by Alembic")
        raise
