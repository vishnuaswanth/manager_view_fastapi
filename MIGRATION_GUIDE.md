# Database Migration Guide

## Overview

This guide covers running Alembic migrations for both SQLite (development) and MSSQL (production).

## Migration Files

### 001_add_bench_allocation_and_fix_workhours.py

**Changes:**
1. Adds `BenchAllocationCompleted` (BOOLEAN, NOT NULL, default=False) to `AllocationExecutionModel`
2. Adds `BenchAllocationCompletedAt` (DATETIME, nullable) to `AllocationExecutionModel`
3. Changes `WorkHours` type from INTEGER to FLOAT in `MonthConfigurationModel`

**Compatibility:**
- ✅ SQLite (DEBUG mode) - Uses batch mode with table recreation
- ✅ MSSQL (PRODUCTION mode) - Uses direct ALTER TABLE statements

---

## Running Migrations

### Development (SQLite)

```bash
# Check current migration status
alembic current

# Show pending migrations
alembic history

# Apply all pending migrations
alembic upgrade head

# Verify migration applied
alembic current
```

### Production (MSSQL)

**IMPORTANT: Test on staging database first!**

```bash
# 1. Backup production database
# Run this in MSSQL Management Studio or via sqlcmd

# 2. Set MODE to PRODUCTION in code/config.ini
# [settings]
# mode = PRODUCTION

# 3. Check current migration status
alembic current

# 4. Preview migration SQL (dry-run)
alembic upgrade head --sql > migration_preview.sql
# Review migration_preview.sql before applying

# 5. Apply migration
alembic upgrade head

# 6. Verify migration
alembic current

# 7. Verify columns exist
# In MSSQL:
# SELECT * FROM INFORMATION_SCHEMA.COLUMNS
# WHERE TABLE_NAME = 'allocationexecutionmodel'
# AND COLUMN_NAME IN ('BenchAllocationCompleted', 'BenchAllocationCompletedAt')
```

---

## Migration Details

### Change 1: Add BenchAllocationCompleted Columns

**Purpose:** Track when bench allocation has been completed for an execution.

**SQL (MSSQL equivalent):**
```sql
ALTER TABLE allocationexecutionmodel
ADD BenchAllocationCompleted BIT NOT NULL DEFAULT 0;

ALTER TABLE allocationexecutionmodel
ADD BenchAllocationCompletedAt DATETIME NULL;
```

**Impact:**
- Existing records: `BenchAllocationCompleted` will be `False` (0)
- Existing records: `BenchAllocationCompletedAt` will be `NULL`
- No data loss
- Safe for production

### Change 2: WorkHours Type Change (INTEGER → FLOAT)

**Purpose:** Support decimal work hours (e.g., 7.5 hours, 8.25 hours).

**SQL (MSSQL equivalent):**
```sql
ALTER TABLE monthconfigurationmodel
ALTER COLUMN WorkHours FLOAT NOT NULL;
```

**Impact:**
- Existing integer values preserved (e.g., 9 → 9.0)
- No data loss
- Safe for production

**Data Conversion:**
- 8 → 8.0
- 9 → 9.0
- Values remain functionally identical

---

## Rollback (If Needed)

### Rollback One Migration

```bash
# Rollback last migration
alembic downgrade -1

# Verify rollback
alembic current
```

### Rollback to Specific Version

```bash
# Rollback to specific revision
alembic downgrade <revision_id>

# Example: Rollback to base (before all migrations)
alembic downgrade base
```

---

## Troubleshooting

### Error: "Cannot add a NOT NULL column with default value NULL"

**Solution:** Already fixed in migration file using `server_default='0'`

### Error: "near ALTER: syntax error" (SQLite)

**Solution:** Already fixed - migration uses `batch_alter_table` mode

**Verification:**
- Check `alembic.ini` has: `render_as_batch = true`
- Check `alembic/env.py` has: `render_as_batch=is_sqlite`

### Error: "Table already has column BenchAllocationCompleted"

**Cause:** Column already exists in database (possibly from manual ALTER)

**Solution:**
```bash
# Mark migration as applied without running it
alembic stamp head

# Verify
alembic current
```

### Error: Migration fails mid-execution

**Recovery:**
```bash
# Check current state
alembic current

# If partially applied:
# Option 1: Rollback and retry
alembic downgrade -1
alembic upgrade head

# Option 2: Manual fix in database, then stamp
# Fix issues in database manually
alembic stamp head
```

---

## Verification Queries

### SQLite (Development)

```bash
# Check AllocationExecutionModel schema
sqlite3 code/test.db "PRAGMA table_info(allocationexecutionmodel);"

# Verify BenchAllocationCompleted column
sqlite3 code/test.db "SELECT sql FROM sqlite_master WHERE name='allocationexecutionmodel';"

# Check MonthConfigurationModel schema
sqlite3 code/test.db "PRAGMA table_info(monthconfigurationmodel);"
```

### MSSQL (Production)

```sql
-- Check AllocationExecutionModel columns
SELECT
    COLUMN_NAME,
    DATA_TYPE,
    IS_NULLABLE,
    COLUMN_DEFAULT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'allocationexecutionmodel'
AND COLUMN_NAME IN ('BenchAllocationCompleted', 'BenchAllocationCompletedAt')
ORDER BY ORDINAL_POSITION;

-- Check WorkHours type
SELECT
    COLUMN_NAME,
    DATA_TYPE,
    IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'monthconfigurationmodel'
AND COLUMN_NAME = 'WorkHours';

-- Verify existing data preserved
SELECT TOP 5 * FROM monthconfigurationmodel;
```

---

## Pre-Migration Checklist

### Development (SQLite)

- [ ] Backup `code/test.db`: `cp code/test.db code/test.db.backup`
- [ ] Set MODE=DEBUG in `code/config.ini`
- [ ] Run: `alembic current` to check status
- [ ] Run: `alembic upgrade head`
- [ ] Verify: Check schema with `sqlite3 code/test.db "PRAGMA table_info(allocationexecutionmodel);"`

### Production (MSSQL)

- [ ] **CRITICAL:** Backup production database (full backup + transaction log)
- [ ] Test migration on staging/test database first
- [ ] Schedule maintenance window (migration is fast but be safe)
- [ ] Set MODE=PRODUCTION in `code/config.ini`
- [ ] Preview SQL: `alembic upgrade head --sql > preview.sql`
- [ ] Review preview.sql with DBA
- [ ] Run: `alembic upgrade head`
- [ ] Verify: Run verification queries (see above)
- [ ] Monitor: Check application logs after migration
- [ ] Document: Record migration timestamp and version

---

## Migration Timeline Estimate

### SQLite (Development)
- Backup: < 1 second
- Migration: < 5 seconds
- Verification: < 1 second
- **Total: ~5 seconds**

### MSSQL (Production)
- Backup: Depends on database size (assume 5-30 minutes)
- Migration: < 10 seconds (schema changes only)
- Verification: < 30 seconds
- **Total: ~5-30 minutes (mostly backup time)**

**Note:** Actual migration is very fast (< 10 seconds) as it's schema-only with no data transformation.

---

## Post-Migration Testing

### Verify Application Still Works

```bash
# Start application
python3 -m uvicorn code.main:app --reload --port 8888

# Test bench allocation preview
curl -X POST "http://localhost:8888/api/bench-allocation/preview" \
  -H "Content-Type: application/json" \
  -d '{"month": "April", "year": 2025}'

# Test bench allocation update
curl -X POST "http://localhost:8888/api/bench-allocation/update" \
  -H "Content-Type: application/json" \
  -d '{ ... }'

# Verify BenchAllocationCompleted is set
curl "http://localhost:8888/api/allocation-reports?month=April&year=2025"
# Check: "bench_allocation_completed": true
```

---

## Emergency Rollback Procedure (Production)

**If migration causes issues:**

```bash
# 1. Stop application immediately
# Kill uvicorn process

# 2. Rollback migration
alembic downgrade -1

# 3. Verify rollback
alembic current

# 4. Restart application
python3 -m uvicorn code.main:app --reload --port 8888

# 5. Verify application works

# 6. Investigate issue before retrying migration
```

**If rollback fails:**
```sql
-- Manual rollback in MSSQL
BEGIN TRANSACTION;

-- Drop new columns
ALTER TABLE allocationexecutionmodel DROP COLUMN BenchAllocationCompletedAt;
ALTER TABLE allocationexecutionmodel DROP COLUMN BenchAllocationCompleted;

-- Revert WorkHours type (data loss possible - use backup!)
-- IMPORTANT: This may truncate decimal values!
ALTER TABLE monthconfigurationmodel
ALTER COLUMN WorkHours INT NOT NULL;

-- Verify before committing
SELECT * FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME IN ('allocationexecutionmodel', 'monthconfigurationmodel');

COMMIT; -- Or ROLLBACK if issues
```

---

## Best Practices

1. **Always backup before migrations** (especially production)
2. **Test on staging first** for production migrations
3. **Review SQL preview** before applying to production
4. **Schedule maintenance windows** for production migrations
5. **Verify after migration** using verification queries
6. **Monitor application logs** for 24 hours after production migration
7. **Keep rollback plan ready** (test rollback on staging too)
8. **Document migrations** (when applied, by whom, any issues)

---

## Support

If you encounter issues not covered here:

1. Check Alembic logs: `alembic.log` (if configured)
2. Check application logs: `code/app.log`
3. Review migration file: `alembic/versions/001_add_bench_allocation_and_fix_workhours.py`
4. Check Alembic history: `alembic history --verbose`

---

**Last Updated:** January 2026
