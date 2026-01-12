# Type Reference - Quick Guide

## TL;DR - Safe Type Migration Patterns

### ✅ Use These Type Patterns (Database-Agnostic)

```python
# Boolean (works on both SQLite and MSSQL)
sa.Column('field_name', sa.Boolean(), nullable=False, server_default='0')
# SQLite: INTEGER (0/1)
# MSSQL: BIT (0/1)

# Float (works on both)
sa.Column('field_name', sa.Float(), nullable=False)
# SQLite: REAL
# MSSQL: FLOAT

# DateTime (works on both)
sa.Column('field_name', sa.DateTime(), nullable=False, server_default=sa.func.now())
# SQLite: TEXT (ISO8601)
# MSSQL: DATETIME

# String with length (works on both)
sa.Column('field_name', sa.String(100), nullable=False)
# SQLite: TEXT
# MSSQL: VARCHAR(100)

# Unlimited text (works on both)
sa.Column('field_name', sa.Text(), nullable=True)
# SQLite: TEXT
# MSSQL: VARCHAR(MAX)

# Integer (works on both)
sa.Column('field_name', sa.Integer(), nullable=False)
# SQLite: INTEGER
# MSSQL: INT
```

---

## Your Current Migrations - Type Breakdown

### Migration 001: Bench Allocation Tracking

#### Column 1: BenchAllocationCompleted
```python
# SQLModel Definition (db.py:442)
BenchAllocationCompleted: bool = Field(default=False, nullable=False)

# Migration Type (001_add_bench_allocation_and_fix_workhours.py)
sa.Column('BenchAllocationCompleted', sa.Boolean(), nullable=False, server_default='0')

# Actual Database Types:
# - SQLite: INTEGER (0 = False, 1 = True)
# - MSSQL: BIT (0 = False, 1 = True)

# server_default='0' ensures:
# - Existing rows get False (0) automatically
# - No NULL constraint violation
# - Works on both databases (string '0' interpreted as integer 0/bit 0)
```

**Why This Works:**
- `sa.Boolean()` is database-agnostic
- SQLAlchemy translates to INTEGER for SQLite, BIT for MSSQL
- `server_default='0'` satisfies NOT NULL constraint for existing rows

---

#### Column 2: BenchAllocationCompletedAt
```python
# SQLModel Definition (db.py:443)
BenchAllocationCompletedAt: Optional[datetime] = Field(sa_column=Column(DateTime, nullable=True))

# Migration Type
sa.Column('BenchAllocationCompletedAt', sa.DateTime(), nullable=True)

# Actual Database Types:
# - SQLite: TEXT (stores as ISO8601: "2025-01-12 10:30:00.123")
# - MSSQL: DATETIME (native timestamp)

# nullable=True ensures:
# - Existing rows get NULL (not set yet)
# - No default value needed
# - Updated when bench allocation completes
```

**Why This Works:**
- `sa.DateTime()` is database-agnostic
- SQLAlchemy handles string↔datetime conversion transparently for SQLite
- NULL is allowed, so no server_default needed

---

#### Column 3: WorkHours (Type Change)
```python
# SQLModel Definition (db.py:369)
WorkHours: float = Field(nullable=False)

# Migration Type Change
batch_op.alter_column(
    'WorkHours',
    existing_type=sa.Integer(),  # Current type in DB
    type_=sa.Float(),             # New type
    existing_nullable=False       # Keep NOT NULL constraint
)

# Type Conversion:
# - SQLite: INTEGER → REAL
# - MSSQL: INT → FLOAT

# Data Preservation:
# - 9 → 9.0 (exact, no loss)
# - All integer values preserved as floating point
```

**Why This Works:**
- INTEGER → FLOAT is a widening conversion (no data loss)
- `batch_alter_table` handles SQLite table recreation
- Works for both databases with same code

---

### Migration 002: History Logging Tables

#### Table 1: history_log

**All column types:**
```python
# Primary key
sa.Column('id', sa.Integer(), nullable=False, primary_key=True)
# SQLite: INTEGER PRIMARY KEY (auto-increment)
# MSSQL: INT IDENTITY(1,1)

# UUID identifier (string-based)
sa.Column('history_log_id', sa.String(36), nullable=False, unique=True)
# SQLite: TEXT (36 chars)
# MSSQL: VARCHAR(36)
# UUID format: "550e8400-e29b-41d4-a716-446655440000" = 36 chars

# Time period
sa.Column('Month', sa.String(15), nullable=False)
sa.Column('Year', sa.Integer(), nullable=False)
# SQLite: TEXT (15 chars), INTEGER
# MSSQL: VARCHAR(15), INT
# Max month name: "September" = 9 chars (15 gives buffer)

# Change metadata
sa.Column('ChangeType', sa.String(50), nullable=False)
sa.Column('Timestamp', sa.DateTime(), nullable=False, server_default=sa.func.now())
sa.Column('User', sa.String(100), nullable=False)
sa.Column('Description', sa.Text(), nullable=True)
# SQLite: TEXT (50), TEXT (timestamp), TEXT (100), TEXT
# MSSQL: VARCHAR(50), DATETIME, VARCHAR(100), VARCHAR(MAX)

# Statistics
sa.Column('RecordsModified', sa.Integer(), nullable=False)
sa.Column('SummaryData', sa.Text(), nullable=True)
# SQLite: INTEGER, TEXT
# MSSQL: INT, VARCHAR(MAX)

# Audit trail
sa.Column('CreatedBy', sa.String(100), nullable=False)
sa.Column('CreatedDateTime', sa.DateTime(), nullable=False, server_default=sa.func.now())
# SQLite: TEXT (100), TEXT (timestamp)
# MSSQL: VARCHAR(100), DATETIME
```

**server_default=sa.func.now() translation:**
- SQLite: `DEFAULT CURRENT_TIMESTAMP`
- MSSQL: `DEFAULT GETDATE()`
- SQLAlchemy handles translation automatically

---

#### Table 2: history_change

**All column types:**
```python
# Primary key
sa.Column('id', sa.Integer(), nullable=False, primary_key=True)

# Link to parent
sa.Column('history_log_id', sa.String(36), nullable=False)

# Record identifiers
sa.Column('MainLOB', sa.String(255), nullable=False)
sa.Column('State', sa.String(100), nullable=False)
sa.Column('CaseType', sa.String(255), nullable=False)
sa.Column('CaseID', sa.String(100), nullable=False)

# Field change details
sa.Column('FieldName', sa.String(100), nullable=False)  # "Jun-25.fte_avail"
sa.Column('OldValue', sa.Text(), nullable=True)         # String representation
sa.Column('NewValue', sa.Text(), nullable=True)         # String representation
sa.Column('Delta', sa.Float(), nullable=True)           # Numeric difference

# Month context
sa.Column('MonthLabel', sa.String(15), nullable=True)  # "Jun-25"

# Audit trail
sa.Column('CreatedDateTime', sa.DateTime(), nullable=False, server_default=sa.func.now())
```

---

## Type Mapping Summary Table

| SQLModel Type | SQLAlchemy Type | SQLite Type | MSSQL Type | Notes |
|---------------|-----------------|-------------|------------|-------|
| `bool` | `sa.Boolean()` | `INTEGER` | `BIT` | Use `server_default='0'` for NOT NULL |
| `int` | `sa.Integer()` | `INTEGER` | `INT` | Auto-increment for primary keys |
| `float` | `sa.Float()` | `REAL` | `FLOAT` | 8-byte floating point |
| `str` | `sa.String(N)` | `TEXT` | `VARCHAR(N)` | Always specify length N |
| `str` (unlimited) | `sa.Text()` | `TEXT` | `VARCHAR(MAX)` | For large text fields |
| `datetime` | `sa.DateTime()` | `TEXT` | `DATETIME` | ISO8601 strings in SQLite |
| `Optional[T]` | `nullable=True` | `NULL` | `NULL` | No server_default needed |

---

## Critical Rules for Type Changes

### ✅ SAFE - Always Works

```python
# 1. INTEGER → FLOAT (widening)
batch_op.alter_column('col', existing_type=sa.Integer(), type_=sa.Float())
# Data: 9 → 9.0 (exact, no loss)

# 2. VARCHAR(N) → VARCHAR(M) where M > N (widening)
batch_op.alter_column('col', existing_type=sa.String(50), type_=sa.String(100))
# Data: "hello" stays "hello" (no truncation)

# 3. VARCHAR(N) → TEXT (widening)
batch_op.alter_column('col', existing_type=sa.String(255), type_=sa.Text())
# Data: Any string stays intact

# 4. Adding new column with server_default
batch_op.add_column(sa.Column('col', sa.Boolean(), nullable=False, server_default='0'))
# Existing rows get default value automatically
```

### ⚠️ RISKY - Validate Data First

```python
# 1. FLOAT → INTEGER (narrowing, decimals lost)
batch_op.alter_column('col', existing_type=sa.Float(), type_=sa.Integer())
# Data: 9.7 → 9 (TRUNCATED!)

# 2. VARCHAR(M) → VARCHAR(N) where N < M (narrowing, truncation)
batch_op.alter_column('col', existing_type=sa.String(100), type_=sa.String(50))
# Data > 50 chars: TRUNCATED!

# 3. TEXT → VARCHAR(N) (narrowing, truncation)
batch_op.alter_column('col', existing_type=sa.Text(), type_=sa.String(255))
# Data > 255 chars: TRUNCATED!

# 4. Adding NOT NULL column without server_default
batch_op.add_column(sa.Column('col', sa.Boolean(), nullable=False))
# ERROR: Existing rows can't be NULL!
```

---

## Common Errors and Fixes

### Error 1: "Cannot add NOT NULL column"
```python
# ❌ WRONG - Missing server_default
sa.Column('field', sa.Boolean(), nullable=False)

# ✅ CORRECT - Add server_default
sa.Column('field', sa.Boolean(), nullable=False, server_default='0')
```

### Error 2: "near ALTER: syntax error" (SQLite)
```python
# ❌ WRONG - Direct ALTER (SQLite doesn't support)
op.alter_column('table', 'col', type_=sa.Float())

# ✅ CORRECT - Use batch mode
with op.batch_alter_table('table', schema=None) as batch_op:
    batch_op.alter_column('col', existing_type=sa.Integer(), type_=sa.Float())
```

### Error 3: Type mismatch between model and migration
```python
# SQLModel (db.py)
WorkHours: float = Field(nullable=False)

# ❌ WRONG - Type mismatch
sa.Column('WorkHours', sa.Integer(), nullable=False)

# ✅ CORRECT - Match the model
sa.Column('WorkHours', sa.Float(), nullable=False)
```

---

## Pre-Deployment Checklist

Before running migrations on production:

- [ ] **1. Verify types match SQLModel definitions**
  ```bash
  # Check db.py models match migration types
  python3 verify_type_consistency.py
  ```

- [ ] **2. Test on SQLite first**
  ```bash
  cp code/test.db code/test.db.backup
  alembic upgrade head
  sqlite3 code/test.db "PRAGMA table_info(allocationexecutionmodel);"
  ```

- [ ] **3. Backup production database**
  ```bash
  # CRITICAL: Full backup + transaction log
  ```

- [ ] **4. Preview MSSQL migration SQL**
  ```bash
  alembic upgrade head --sql > migration_preview.sql
  # Review types in generated SQL
  ```

- [ ] **5. Test on MSSQL staging environment**
  ```bash
  # Apply to staging first
  alembic upgrade head
  # Verify schema
  ```

- [ ] **6. Apply to production**
  ```bash
  # Only after successful staging test
  alembic upgrade head
  ```

---

## Quick Verification Commands

### SQLite Type Check
```bash
# Show all columns and types
sqlite3 code/test.db "PRAGMA table_info(allocationexecutionmodel);"

# Show WorkHours type (should be REAL after migration)
sqlite3 code/test.db "PRAGMA table_info(monthconfigurationmodel);" | grep WorkHours

# Show BenchAllocationCompleted type (should be INTEGER)
sqlite3 code/test.db "PRAGMA table_info(allocationexecutionmodel);" | grep Bench
```

### MSSQL Type Check
```sql
-- Show all columns and types
SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'allocationexecutionmodel'
ORDER BY ORDINAL_POSITION;

-- Check WorkHours type (should be FLOAT)
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'monthconfigurationmodel'
AND COLUMN_NAME = 'WorkHours';

-- Check BenchAllocationCompleted type (should be BIT)
SELECT COLUMN_NAME, DATA_TYPE, COLUMN_DEFAULT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'allocationexecutionmodel'
AND COLUMN_NAME LIKE '%Bench%';
```

---

## Summary

**Your migrations use 100% database-agnostic types:**
- ✅ `sa.Boolean()` → INTEGER (SQLite) or BIT (MSSQL)
- ✅ `sa.Float()` → REAL (SQLite) or FLOAT (MSSQL)
- ✅ `sa.DateTime()` → TEXT (SQLite) or DATETIME (MSSQL)
- ✅ `sa.String(N)` → TEXT (SQLite) or VARCHAR(N) (MSSQL)
- ✅ `sa.Text()` → TEXT (SQLite) or VARCHAR(MAX) (MSSQL)
- ✅ `sa.Integer()` → INTEGER (SQLite) or INT (MSSQL)

**All type changes are safe:**
- ✅ INTEGER → FLOAT (widening, no data loss)
- ✅ New columns use `server_default` for NOT NULL
- ✅ batch_alter_table works on both databases
- ✅ Idempotent (checks existence before operations)
- ✅ Transaction-safe (automatic rollback on error)

**Ready to deploy to production!**
