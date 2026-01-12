"""add bench allocation tracking and fix workhours type

Revision ID: 001_initial
Revises:
Create Date: 2026-01-12 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mssql, sqlite
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def column_exists(table_name, column_name):
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    """
    Add bench allocation tracking columns and fix WorkHours type.

    Compatible with both SQLite (development) and MSSQL (production).
    Uses batch mode for SQLite and direct ALTER for MSSQL.

    Safely checks if columns exist before adding them.
    """

    # ============================================================
    # CHANGE 1: Add BenchAllocationCompleted columns
    # ============================================================

    # Check if columns already exist
    bench_completed_exists = column_exists('allocationexecutionmodel', 'BenchAllocationCompleted')
    bench_completed_at_exists = column_exists('allocationexecutionmodel', 'BenchAllocationCompletedAt')

    if not bench_completed_exists or not bench_completed_at_exists:
        # Use batch_alter_table for SQLite compatibility
        with op.batch_alter_table('allocationexecutionmodel', schema=None) as batch_op:
            if not bench_completed_exists:
                print("Adding BenchAllocationCompleted column...")
                batch_op.add_column(
                    sa.Column(
                        'BenchAllocationCompleted',
                        sa.Boolean(),
                        nullable=False,
                        server_default='0'  # Required for SQLite when adding NOT NULL
                    )
                )
            else:
                print("BenchAllocationCompleted column already exists, skipping...")

            if not bench_completed_at_exists:
                print("Adding BenchAllocationCompletedAt column...")
                batch_op.add_column(
                    sa.Column(
                        'BenchAllocationCompletedAt',
                        sa.DateTime(),
                        nullable=True
                    )
                )
            else:
                print("BenchAllocationCompletedAt column already exists, skipping...")
    else:
        print("Both BenchAllocation columns already exist, skipping...")

    # ============================================================
    # CHANGE 2: Change WorkHours from INTEGER to FLOAT
    # ============================================================

    # Check current type of WorkHours
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    columns = inspector.get_columns('monthconfigurationmodel')
    workhours_col = next((col for col in columns if col['name'] == 'WorkHours'), None)

    if workhours_col:
        current_type = str(workhours_col['type']).upper()
        print(f"Current WorkHours type: {current_type}")

        # Check if it's already FLOAT/REAL (SQLite uses REAL for FLOAT)
        if 'FLOAT' not in current_type and 'REAL' not in current_type and 'DOUBLE' not in current_type:
            print("Converting WorkHours from INTEGER to FLOAT...")
            # Use batch_alter_table for SQLite compatibility
            with op.batch_alter_table('monthconfigurationmodel', schema=None) as batch_op:
                batch_op.alter_column(
                    'WorkHours',
                    existing_type=sa.Integer(),
                    type_=sa.Float(),
                    existing_nullable=False
                )
        else:
            print("WorkHours is already FLOAT type, skipping...")
    else:
        print("WARNING: WorkHours column not found!")


def downgrade() -> None:
    """
    Revert bench allocation tracking columns and WorkHours type.

    Compatible with both SQLite and MSSQL.
    """

    # ============================================================
    # REVERT CHANGE 2: Change WorkHours back to INTEGER
    # ============================================================

    # Check if column exists and is FLOAT
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    columns = inspector.get_columns('monthconfigurationmodel')
    workhours_col = next((col for col in columns if col['name'] == 'WorkHours'), None)

    if workhours_col:
        current_type = str(workhours_col['type']).upper()
        if 'FLOAT' in current_type or 'REAL' in current_type or 'DOUBLE' in current_type:
            print("Reverting WorkHours from FLOAT to INTEGER...")
            with op.batch_alter_table('monthconfigurationmodel', schema=None) as batch_op:
                batch_op.alter_column(
                    'WorkHours',
                    existing_type=sa.Float(),
                    type_=sa.Integer(),
                    existing_nullable=False
                )
        else:
            print("WorkHours is already INTEGER type, skipping...")

    # ============================================================
    # REVERT CHANGE 1: Remove BenchAllocationCompleted columns
    # ============================================================

    bench_completed_exists = column_exists('allocationexecutionmodel', 'BenchAllocationCompleted')
    bench_completed_at_exists = column_exists('allocationexecutionmodel', 'BenchAllocationCompletedAt')

    if bench_completed_exists or bench_completed_at_exists:
        with op.batch_alter_table('allocationexecutionmodel', schema=None) as batch_op:
            if bench_completed_at_exists:
                print("Dropping BenchAllocationCompletedAt column...")
                batch_op.drop_column('BenchAllocationCompletedAt')
            else:
                print("BenchAllocationCompletedAt column doesn't exist, skipping...")

            if bench_completed_exists:
                print("Dropping BenchAllocationCompleted column...")
                batch_op.drop_column('BenchAllocationCompleted')
            else:
                print("BenchAllocationCompleted column doesn't exist, skipping...")
    else:
        print("Both BenchAllocation columns already removed, skipping...")
