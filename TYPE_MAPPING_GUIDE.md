# Database Type Mapping Guide

## Overview

This guide explains how to handle type definitions and field type changes in migrations that must work with both SQLite (development/testing) and MSSQL (production with client data).

## Critical Type Mapping Issues

### 1. Boolean Type Mapping

**SQLModel Definition:**
```python
BenchAllocationCompleted: bool = Field(default=False, nullable=False)
```

**Database Types:**
- **SQLite**: No native BOOLEAN type → Uses `INTEGER` (0 = False, 1 = True)
- **MSSQL**: Native `BIT` type (0 = False, 1 = True)
- **SQLAlchemy**: Uses `sa.Boolean()` which translates correctly to both

**Migration Implementation:**
```python
sa.Column('BenchAllocationCompleted', sa.Boolean(), nullable=False, server_default='0')
```

**Why This Works:**
- SQLAlchemy translates `sa.Boolean()` to INTEGER for SQLite, BIT for MSSQL
- `server_default='0'` works for both (string interpreted as 0 in both DBs)
- No need for dialect-specific logic

---

### 2. Float Type Mapping

**SQLModel Definition:**
```python
WorkHours: float = Field(nullable=False)
```

**Database Types:**
- **SQLite**: `REAL` (double-precision floating point)
- **MSSQL**: `FLOAT` (8-byte floating point)
- **SQLAlchemy**: Uses `sa.Float()` which translates correctly to both

**Migration Implementation:**
```python
batch_op.alter_column('WorkHours', existing_type=sa.Integer(), type_=sa.Float(), existing_nullable=False)
```

**Data Preservation:**
- INTEGER → FLOAT conversion is lossless
- 9 → 9.0 (exact representation)
- No data loss, no precision issues

---

### 3. DateTime Type Mapping

**SQLModel Definition:**
```python
BenchAllocationCompletedAt: Optional[datetime] = Field(sa_column=Column(DateTime, nullable=True))
Timestamp: datetime = Field(sa_column=Column(DateTime, nullable=False, server_default=func.now()))
```

**Database Types:**
- **SQLite**: `TEXT` (ISO8601 strings: "YYYY-MM-DD HH:MM:SS.SSS")
- **MSSQL**: `DATETIME` (native timestamp type)
- **SQLAlchemy**: Uses `sa.DateTime()` which handles conversion transparently

**Migration Implementation:**
```python
sa.Column('BenchAllocationCompletedAt', sa.DateTime(), nullable=True)
sa.Column('Timestamp', sa.DateTime(), nullable=False, server_default=sa.func.now())
```

**Server Defaults:**
- `sa.func.now()` translates to:
  - SQLite: `CURRENT_TIMESTAMP`
  - MSSQL: `GETDATE()`

---

### 4. String Type Mapping

**SQLModel Definition:**
```python
Month: str = Field(sa_column=Column(String(15), nullable=False))
history_log_id: str = Field(sa_column=Column(String(36), nullable=False, unique=True))
```

**Database Types:**
- **SQLite**: `TEXT` (dynamic, but respects length for compatibility)
- **MSSQL**: `VARCHAR(N)` or `NVARCHAR(N)`
- **SQLAlchemy**: Uses `sa.String(N)` which translates correctly

**Migration Implementation:**
```python
sa.Column('Month', sa.String(15), nullable=False)
sa.Column('history_log_id', sa.String(36), nullable=False, unique=True)
```

**Best Practices:**
- Always specify length for String types
- Use String(36) for UUIDs (36 chars with hyphens)
- Use String(255) for general text fields
- Use Text() for unlimited length text

---

### 5. Integer Type Mapping

**SQLModel Definition:**
```python
Year: int = Field(nullable=False)
RecordsModified: int = Field(nullable=False)
```

**Database Types:**
- **SQLite**: `INTEGER` (dynamic size, up to 8 bytes)
- **MSSQL**: `INT` (4 bytes, -2,147,483,648 to 2,147,483,647)
- **SQLAlchemy**: Uses `sa.Integer()` which translates correctly

**Migration Implementation:**
```python
sa.Column('Year', sa.Integer(), nullable=False)
sa.Column('RecordsModified', sa.Integer(), nullable=False)
```

---

## Type Change Migration Patterns

### Pattern 1: Adding New Column (Safe)

**Scenario:** Add new column to existing table

**SQLite:**
```python
with op.batch_alter_table('table_name', schema=None) as batch_op:
    batch_op.add_column(sa.Column('new_column', sa.Boolean(), nullable=False, server_default='0'))
```

**MSSQL:**
```python
op.add_column('table_name', sa.Column('new_column', sa.Boolean(), nullable=False, server_default='0'))
```

**Why batch_alter_table for SQLite:**
- SQLite doesn't support ALTER TABLE ADD COLUMN with constraints in some cases
- Batch mode recreates the table with the new schema
- Safe but slower than direct ALTER

**Migration Code (Unified):**
```python
with op.batch_alter_table('table_name', schema=None) as batch_op:
    batch_op.add_column(sa.Column('new_column', sa.Boolean(), nullable=False, server_default='0'))
```
→ Works for both SQLite and MSSQL!

---

### Pattern 2: Changing Column Type (Risky)

**Scenario:** Change WorkHours from INTEGER to FLOAT

**SQLite:**
- Cannot use ALTER COLUMN TYPE (not supported)
- Must use batch mode (table recreation)
```python
with op.batch_alter_table('table_name', schema=None) as batch_op:
    batch_op.alter_column('WorkHours', existing_type=sa.Integer(), type_=sa.Float(), existing_nullable=False)
```

**MSSQL:**
- Direct ALTER COLUMN supported
- Batch mode still works (translates to ALTER COLUMN)
```python
with op.batch_alter_table('table_name', schema=None) as batch_op:
    batch_op.alter_column('WorkHours', existing_type=sa.Integer(), type_=sa.Float(), existing_nullable=False)
```

**Data Compatibility Matrix:**

| From Type | To Type | SQLite | MSSQL | Data Loss? |
|-----------|---------|--------|-------|------------|
| INTEGER | FLOAT | ✅ Safe | ✅ Safe | None (9 → 9.0) |
| FLOAT | INTEGER | ⚠️ Truncates | ⚠️ Truncates | Decimals lost |
| VARCHAR(50) | VARCHAR(100) | ✅ Safe | ✅ Safe | None |
| VARCHAR(100) | VARCHAR(50) | ⚠️ Truncates | ⚠️ Truncates | Data > 50 chars lost |
| TEXT | VARCHAR(N) | ⚠️ Truncates | ⚠️ Truncates | Data > N chars lost |
| VARCHAR(N) | TEXT | ✅ Safe | ✅ Safe | None |

**Safe Type Changes:**
- INTEGER → FLOAT (widening conversion)
- VARCHAR(N) → VARCHAR(M) where M > N (widening)
- VARCHAR(N) → TEXT (widening)

**Unsafe Type Changes (Require Data Validation):**
- FLOAT → INTEGER (decimals truncated)
- VARCHAR(M) → VARCHAR(N) where N < M (data truncated)
- TEXT → VARCHAR(N) (data > N chars truncated)

---

### Pattern 3: Creating New Table (Safe)

**Scenario:** Create history_log and history_change tables

**Migration Code:**
```python
op.create_table(
    'history_log',
    sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
    sa.Column('history_log_id', sa.String(36), nullable=False, unique=True),
    sa.Column('Month', sa.String(15), nullable=False),
    sa.Column('Year', sa.Integer(), nullable=False),
    sa.Column('ChangeType', sa.String(50), nullable=False),
    sa.Column('Timestamp', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    sa.Column('User', sa.String(100), nullable=False),
    sa.Column('Description', sa.Text(), nullable=True),
    sa.Column('RecordsModified', sa.Integer(), nullable=False),
    sa.Column('SummaryData', sa.Text(), nullable=True),
    sa.Column('CreatedBy', sa.String(100), nullable=False),
    sa.Column('CreatedDateTime', sa.DateTime(), nullable=False, server_default=sa.func.now()),
)
```

**Works identically on SQLite and MSSQL.**

---

## Migration Best Practices

### 1. Use SQLAlchemy Generic Types

**✅ GOOD:**
```python
sa.Column('amount', sa.Float(), nullable=False)
sa.Column('is_active', sa.Boolean(), nullable=False)
sa.Column('created_at', sa.DateTime(), nullable=False)
```

**❌ BAD:**
```python
from sqlalchemy.dialects.mssql import BIT, FLOAT
sa.Column('amount', FLOAT, nullable=False)  # MSSQL-specific!
sa.Column('is_active', BIT, nullable=False)   # MSSQL-specific!
```

### 2. Match SQLModel Field Definitions Exactly

**SQLModel (db.py):**
```python
class MonthConfigurationModel(SQLModel, table=True):
    WorkHours: float = Field(nullable=False)
```

**Migration:**
```python
sa.Column('WorkHours', sa.Float(), nullable=False)
```

→ Types must match: `float` → `sa.Float()`

### 3. Use server_default for NOT NULL Columns

**When adding NOT NULL columns to tables with existing data:**
```python
sa.Column('BenchAllocationCompleted', sa.Boolean(), nullable=False, server_default='0')
```

**Without server_default:**
- SQLite: ERROR - "Cannot add NOT NULL column without default"
- MSSQL: ERROR - "ALTER TABLE only allows columns to be added that can contain nulls"

### 4. Use batch_alter_table for SQLite Compatibility

**For any ALTER operations on SQLite:**
```python
with op.batch_alter_table('table_name', schema=None) as batch_op:
    batch_op.add_column(...)
    batch_op.alter_column(...)
```

**Why:**
- SQLite has limited ALTER TABLE support
- Batch mode recreates table with new schema
- Works on both SQLite and MSSQL (Alembic translates correctly)

### 5. Check Column Existence Before Adding (Idempotent)

**Always check before modifying:**
```python
def column_exists(table_name, column_name):
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns

if not column_exists('allocationexecutionmodel', 'BenchAllocationCompleted'):
    # Add column
```

**Benefits:**
- Safe to run migrations multiple times
- Handles partial failures gracefully
- Useful for production deployments

---

## Type Verification Checklist

Before running migrations in production:

### Step 1: Verify Type Consistency

**Check SQLModel definitions match migration types:**

| SQLModel Field | SQLModel Type | Migration Type | Match? |
|----------------|---------------|----------------|--------|
| WorkHours | `float` | `sa.Float()` | ✅ |
| BenchAllocationCompleted | `bool` | `sa.Boolean()` | ✅ |
| BenchAllocationCompletedAt | `Optional[datetime]` | `sa.DateTime(), nullable=True` | ✅ |
| Month | `str` with `String(15)` | `sa.String(15)` | ✅ |
| Year | `int` | `sa.Integer()` | ✅ |

### Step 2: Test on SQLite First

```bash
# 1. Backup SQLite database
cp code/test.db code/test.db.backup

# 2. Run migration
alembic upgrade head

# 3. Verify schema
sqlite3 code/test.db "PRAGMA table_info(allocationexecutionmodel);"

# 4. Check types
sqlite3 code/test.db "SELECT sql FROM sqlite_master WHERE name='allocationexecutionmodel';"
```

### Step 3: Test on MSSQL (Staging First!)

```bash
# 1. BACKUP DATABASE (critical!)

# 2. Set PRODUCTION mode in config.ini
mode = PRODUCTION

# 3. Preview migration
alembic upgrade head --sql > migration_preview.sql

# 4. Review SQL for type correctness

# 5. Apply migration
alembic upgrade head

# 6. Verify schema
SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'allocationexecutionmodel';
```

---

## Common Type Issues and Solutions

### Issue 1: Boolean Default Value Mismatch

**Error:**
```
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) Cannot add a NOT NULL column with default value NULL
```

**Cause:** Missing server_default for NOT NULL column

**Solution:**
```python
# Before (WRONG):
sa.Column('BenchAllocationCompleted', sa.Boolean(), nullable=False)

# After (CORRECT):
sa.Column('BenchAllocationCompleted', sa.Boolean(), nullable=False, server_default='0')
```

---

### Issue 2: ALTER COLUMN TYPE Not Supported (SQLite)

**Error:**
```
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) near "ALTER": syntax error
```

**Cause:** SQLite doesn't support ALTER COLUMN TYPE

**Solution:**
```python
# Use batch_alter_table:
with op.batch_alter_table('table_name', schema=None) as batch_op:
    batch_op.alter_column('WorkHours', existing_type=sa.Integer(), type_=sa.Float())
```

---

### Issue 3: Type Mismatch Between Model and Migration

**Symptom:** SQLModel creates table with different types than migration

**Example:**
```python
# SQLModel definition (db.py):
WorkHours: float = Field(nullable=False)

# Migration (WRONG):
sa.Column('WorkHours', sa.Integer(), nullable=False)  # ← Type mismatch!
```

**Solution:** Always match types exactly
```python
# Migration (CORRECT):
sa.Column('WorkHours', sa.Float(), nullable=False)
```

---

### Issue 4: String Length Mismatches

**Symptom:** Data truncation errors in MSSQL

**Example:**
```python
# SQLModel:
history_log_id: str = Field(sa_column=Column(String(36), nullable=False))

# Migration (WRONG):
sa.Column('history_log_id', sa.String(20), nullable=False)  # ← Too short for UUID!
```

**Solution:** Match string lengths exactly
```python
# Migration (CORRECT):
sa.Column('history_log_id', sa.String(36), nullable=False)  # UUID = 36 chars
```

---

## Type Mapping Reference

### Quick Reference Table

| Python Type | SQLModel Type | SQLAlchemy Type | SQLite Type | MSSQL Type |
|-------------|---------------|-----------------|-------------|------------|
| `int` | `Field()` | `sa.Integer()` | `INTEGER` | `INT` |
| `float` | `Field()` | `sa.Float()` | `REAL` | `FLOAT` |
| `bool` | `Field()` | `sa.Boolean()` | `INTEGER` | `BIT` |
| `str` | `Field()` | `sa.String(N)` | `TEXT` | `VARCHAR(N)` |
| `str` (unlimited) | `Field(sa_column=Column(Text))` | `sa.Text()` | `TEXT` | `VARCHAR(MAX)` |
| `datetime` | `Field(sa_column=Column(DateTime))` | `sa.DateTime()` | `TEXT` | `DATETIME` |
| `Optional[T]` | `Field(nullable=True)` | `nullable=True` | `NULL allowed` | `NULL allowed` |

---

## Migration Code Template

```python
"""description of migration

Revision ID: xxx
Revises: yyy
Create Date: 2026-01-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision = 'xxx'
down_revision = 'yyy'

def column_exists(table_name, column_name):
    """Check if column exists."""
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns

def upgrade() -> None:
    """
    Description of changes.

    TRANSACTION SAFETY:
    - Uses Alembic's transaction context (auto-rollback on error)
    - Idempotent (checks existence before operations)
    - Compatible with SQLite and MSSQL
    """
    conn = op.get_bind()

    try:
        # Check existence first (idempotent)
        if not column_exists('table_name', 'new_column'):
            # Use batch_alter_table for SQLite compatibility
            with op.batch_alter_table('table_name', schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column(
                        'new_column',
                        sa.Boolean(),  # ← Use SQLAlchemy generic types
                        nullable=False,
                        server_default='0'  # ← Required for NOT NULL
                    )
                )
            print("✓ Added new_column")
        else:
            print("→ new_column already exists, skipping...")

        print("\n✅ Migration completed successfully!")

    except Exception as e:
        print(f"\n❌ ERROR during migration: {e}")
        print("⚠️  Transaction will be rolled back automatically by Alembic")
        raise  # Re-raise to trigger rollback

def downgrade() -> None:
    """Rollback changes."""
    conn = op.get_bind()

    try:
        if column_exists('table_name', 'new_column'):
            with op.batch_alter_table('table_name', schema=None) as batch_op:
                batch_op.drop_column('new_column')
            print("✓ Dropped new_column")

        print("\n✅ Migration downgrade completed successfully!")

    except Exception as e:
        print(f"\n❌ ERROR during downgrade: {e}")
        print("⚠️  Transaction will be rolled back automatically by Alembic")
        raise
```

---

## Summary

**Key Principles:**
1. ✅ Use SQLAlchemy generic types (`sa.Boolean()`, `sa.Float()`, etc.) - NOT dialect-specific types
2. ✅ Match SQLModel field types exactly in migrations
3. ✅ Use `server_default` when adding NOT NULL columns to existing tables
4. ✅ Use `batch_alter_table` for all ALTER operations (SQLite compatibility)
5. ✅ Check column/table existence before operations (idempotent)
6. ✅ Wrap in try/except to ensure automatic rollback on error
7. ✅ Test on SQLite first, then MSSQL staging, then production

**Safe Type Changes:**
- INTEGER → FLOAT ✅
- VARCHAR(N) → VARCHAR(M) where M > N ✅
- VARCHAR(N) → TEXT ✅
- Adding new columns with server_default ✅

**Risky Type Changes (Validate Data First):**
- FLOAT → INTEGER ⚠️ (decimals truncated)
- VARCHAR(M) → VARCHAR(N) where N < M ⚠️ (data truncated)
- TEXT → VARCHAR(N) ⚠️ (data > N chars truncated)

**Ready to Run:** Use this guide when creating new migrations or troubleshooting type issues.
