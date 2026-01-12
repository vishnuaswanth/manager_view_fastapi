"""add bench allocation tracking and fix workhours type

Revision ID: 001_initial
Revises:
Create Date: 2026-01-12 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql, sqlite


# revision identifiers, used by Alembic.
revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add bench allocation tracking columns and fix WorkHours type.

    Compatible with both SQLite (development) and MSSQL (production).
    Uses batch mode for SQLite and direct ALTER for MSSQL.
    """

    # ============================================================
    # CHANGE 1: Add BenchAllocationCompleted columns
    # ============================================================

    # Use batch_alter_table for SQLite compatibility
    # This will work for both SQLite (recreates table) and MSSQL (direct ALTER)
    with op.batch_alter_table('allocationexecutionmodel', schema=None) as batch_op:
        # Add BenchAllocationCompleted with server default for SQLite
        batch_op.add_column(
            sa.Column(
                'BenchAllocationCompleted',
                sa.Boolean(),
                nullable=False,
                server_default='0'  # Required for SQLite when adding NOT NULL
            )
        )
        batch_op.add_column(
            sa.Column(
                'BenchAllocationCompletedAt',
                sa.DateTime(),
                nullable=True
            )
        )

    # ============================================================
    # CHANGE 2: Change WorkHours from INTEGER to FLOAT
    # ============================================================

    # Use batch_alter_table for SQLite compatibility
    # SQLite: Recreates table with new column type
    # MSSQL: Uses ALTER COLUMN TYPE (supported)
    with op.batch_alter_table('monthconfigurationmodel', schema=None) as batch_op:
        batch_op.alter_column(
            'WorkHours',
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=False
        )


def downgrade() -> None:
    """
    Revert bench allocation tracking columns and WorkHours type.

    Compatible with both SQLite and MSSQL.
    """

    # ============================================================
    # REVERT CHANGE 2: Change WorkHours back to INTEGER
    # ============================================================

    with op.batch_alter_table('monthconfigurationmodel', schema=None) as batch_op:
        batch_op.alter_column(
            'WorkHours',
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=False
        )

    # ============================================================
    # REVERT CHANGE 1: Remove BenchAllocationCompleted columns
    # ============================================================

    with op.batch_alter_table('allocationexecutionmodel', schema=None) as batch_op:
        batch_op.drop_column('BenchAllocationCompletedAt')
        batch_op.drop_column('BenchAllocationCompleted')
