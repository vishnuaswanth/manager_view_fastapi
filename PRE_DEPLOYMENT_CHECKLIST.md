# Pre-Deployment Checklist for Database Migrations

## Purpose

This checklist ensures type safety and data integrity when deploying migrations to production. Follow ALL steps before running `alembic upgrade head` on production.

---

## Phase 1: Type Safety Verification

### ✅ Step 1: Review Type Documentation

Read these documents to understand type handling:

- [ ] **TYPE_REFERENCE_QUICK.md** - Quick reference (5 minutes)
- [ ] **TYPE_MAPPING_GUIDE.md** - Comprehensive guide (optional, 15 minutes)

**Key Concepts to Understand:**
- `sa.Boolean()` → INTEGER (SQLite) or BIT (MSSQL)
- `sa.Float()` → REAL (SQLite) or FLOAT (MSSQL)
- `server_default='0'` required for NOT NULL columns with existing data
- `batch_alter_table` required for SQLite ALTER operations

---

### ✅ Step 2: Verify Type Consistency

Run the automated type verification script:

```bash
python3 verify_type_consistency.py
```

**Expected Output:**
```
============================================================
Verifying SQLite Database Types
============================================================

Checking table: allocationexecutionmodel
  ✅ BenchAllocationCompleted: INTEGER → BOOLEAN
  ✅ BenchAllocationCompletedAt: TEXT → DATETIME

Checking table: monthconfigurationmodel
  ✅ WorkHours: REAL → FLOAT

Checking table: history_log
  ✅ id: INTEGER → INTEGER
  ✅ history_log_id: TEXT → VARCHAR
  ... (all columns)

============================================================
Summary: 25/25 columns verified
============================================================

✅ All column types match expected types!
✅ Safe to run migrations in production
```

**If Verification Fails:**
- ❌ DO NOT proceed to production
- Review error messages
- Check TYPE_MAPPING_GUIDE.md for solutions
- Fix type mismatches in migrations
- Re-run verification

---

## Phase 2: SQLite Testing (Development Environment)

### ✅ Step 3: Backup SQLite Database

```bash
# Create timestamped backup
cp code/test.db code/test.db.backup.$(date +%Y%m%d_%H%M%S)

# Verify backup exists
ls -lh code/test.db.backup.*
```

---

### ✅ Step 4: Check Current Migration Status

```bash
alembic current
```

**Expected Output:**
```
# If no migrations applied yet:
(empty)

# If migration 001 already applied:
001_initial (head)

# If migration 002 already applied:
002_history_tables (head)
```

**Record Current State:**
- Current revision: ___________________
- Need to apply: ___________________

---

### ✅ Step 5: Run Migrations on SQLite

```bash
alembic upgrade head
```

**Expected Output:**
```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 001_initial, add bench allocation tracking and fix workhours type
✓ Adding BenchAllocationCompleted column...
✓ Adding BenchAllocationCompletedAt column...
✓ Converting WorkHours from INTEGER to FLOAT...
✅ Migration 001 completed successfully!
INFO  [alembic.runtime.migration] Running upgrade 001_initial -> 002_history_tables, create history log and history change tables
✓ Creating history_log table...
✓ Creating history_change table...
✅ Migration 002 completed successfully!
```

**If Migration Fails:**
- Check error message carefully
- Migration will auto-rollback (no partial state)
- Restore from backup if needed: `cp code/test.db.backup.* code/test.db`
- Review TYPE_MAPPING_GUIDE.md for solutions
- Fix migration and retry

---

### ✅ Step 6: Verify SQLite Schema

Check that columns were created with correct types:

```bash
# Verify AllocationExecutionModel
sqlite3 code/test.db "PRAGMA table_info(allocationexecutionmodel);" | grep -i bench

# Expected output:
# BenchAllocationCompleted|INTEGER|1||0
# BenchAllocationCompletedAt|TEXT|0||

# Verify MonthConfigurationModel
sqlite3 code/test.db "PRAGMA table_info(monthconfigurationmodel);" | grep -i workhours

# Expected output:
# WorkHours|REAL|1||

# Verify history tables exist
sqlite3 code/test.db ".tables" | grep -i history

# Expected output:
# history_change  history_log
```

**Verification Results:**
- [ ] BenchAllocationCompleted exists (type: INTEGER)
- [ ] BenchAllocationCompletedAt exists (type: TEXT)
- [ ] WorkHours type changed to REAL
- [ ] history_log table exists
- [ ] history_change table exists

---

### ✅ Step 7: Test Application with Migrated SQLite Database

```bash
# Start application
python3 -m uvicorn code.main:app --reload --port 8888

# Test bench allocation API
curl -X POST "http://localhost:8888/api/bench-allocation/preview" \
  -H "Content-Type: application/json" \
  -d '{"month": "April", "year": 2025}'

# Test history log API
curl "http://localhost:8888/api/history-log?page=1&limit=10"
```

**Verification Results:**
- [ ] Application starts without errors
- [ ] Bench allocation endpoints work
- [ ] History log endpoints work
- [ ] No type-related errors in logs

---

## Phase 3: MSSQL Staging Testing (Pre-Production)

### ✅ Step 8: Backup MSSQL Database

**CRITICAL: Full backup + transaction log backup**

```sql
-- In MSSQL Management Studio or sqlcmd
BACKUP DATABASE [YourDatabase]
TO DISK = 'C:\Backups\YourDatabase_PreMigration_20260112.bak'
WITH FORMAT, INIT, NAME = 'Pre-Migration Backup';

-- Also backup transaction log
BACKUP LOG [YourDatabase]
TO DISK = 'C:\Backups\YourDatabase_Log_20260112.trn';
```

**Backup Verification:**
- [ ] Full backup completed successfully
- [ ] Transaction log backup completed
- [ ] Backup files exist and have non-zero size
- [ ] Backup timestamp recorded: ___________________

---

### ✅ Step 9: Set Production Mode

Edit `code/config.ini`:

```ini
[settings]
mode = PRODUCTION  # ← Must be PRODUCTION for MSSQL

[mysql]
user = your_user
password = your_password
host = your_host
port = your_port
database = your_database
```

**Verification:**
- [ ] MODE set to PRODUCTION in config.ini
- [ ] MSSQL credentials correct
- [ ] Can connect to MSSQL database

---

### ✅ Step 10: Preview MSSQL Migration SQL

Generate SQL without applying:

```bash
alembic upgrade head --sql > migration_preview_mssql.sql
```

Review the generated SQL file:

```bash
cat migration_preview_mssql.sql
```

**Check for:**
- [ ] Correct table names
- [ ] Correct column types (BIT for boolean, FLOAT for float, DATETIME for datetime)
- [ ] server_default='0' for BenchAllocationCompleted
- [ ] No unexpected DROP statements
- [ ] No unsafe type conversions

**Example Expected SQL:**
```sql
-- Migration 001
ALTER TABLE allocationexecutionmodel ADD BenchAllocationCompleted BIT NOT NULL DEFAULT 0;
ALTER TABLE allocationexecutionmodel ADD BenchAllocationCompletedAt DATETIME NULL;
ALTER TABLE monthconfigurationmodel ALTER COLUMN WorkHours FLOAT NOT NULL;

-- Migration 002
CREATE TABLE history_log (
    id INT NOT NULL IDENTITY,
    history_log_id VARCHAR(36) NOT NULL,
    Month VARCHAR(15) NOT NULL,
    Year INT NOT NULL,
    ...
);
```

---

### ✅ Step 11: Apply Migrations to MSSQL Staging

```bash
alembic upgrade head
```

**Expected Output:**
```
INFO  [alembic.runtime.migration] Context impl MSSQLImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 001_initial
✓ Adding BenchAllocationCompleted column...
✓ Adding BenchAllocationCompletedAt column...
✓ Converting WorkHours from INTEGER to FLOAT...
✅ Migration 001 completed successfully!
INFO  [alembic.runtime.migration] Running upgrade 001_initial -> 002_history_tables
✓ Creating history_log table...
✓ Creating history_change table...
✅ Migration 002 completed successfully!
```

**If Migration Fails:**
- Transaction will auto-rollback
- Restore from backup if needed
- Review error message
- Fix migration and retry

---

### ✅ Step 12: Verify MSSQL Schema

```sql
-- Check AllocationExecutionModel columns
SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'allocationexecutionmodel'
AND COLUMN_NAME IN ('BenchAllocationCompleted', 'BenchAllocationCompletedAt')
ORDER BY ORDINAL_POSITION;

-- Expected:
-- BenchAllocationCompleted | bit | NO | ((0))
-- BenchAllocationCompletedAt | datetime | YES | NULL

-- Check WorkHours type
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'monthconfigurationmodel'
AND COLUMN_NAME = 'WorkHours';

-- Expected:
-- WorkHours | float

-- Check history tables exist
SELECT TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_NAME IN ('history_log', 'history_change');

-- Expected:
-- history_log
-- history_change
```

**Verification Results:**
- [ ] BenchAllocationCompleted: BIT NOT NULL DEFAULT 0
- [ ] BenchAllocationCompletedAt: DATETIME NULL
- [ ] WorkHours: FLOAT NOT NULL
- [ ] history_log table exists
- [ ] history_change table exists

---

### ✅ Step 13: Test Application with MSSQL Staging

```bash
# Ensure MODE=PRODUCTION in config.ini
python3 -m uvicorn code.main:app --reload --port 8888

# Test bench allocation
curl -X POST "http://localhost:8888/api/bench-allocation/preview" \
  -H "Content-Type: application/json" \
  -d '{"month": "April", "year": 2025}'

# Test history log
curl "http://localhost:8888/api/history-log?page=1&limit=10"

# Check for type-related errors
tail -n 100 code/app.log | grep -i "type\|error"
```

**Verification Results:**
- [ ] Application starts without errors
- [ ] Can connect to MSSQL database
- [ ] Bench allocation endpoints work
- [ ] History log endpoints work
- [ ] No type-related errors
- [ ] Data reads/writes correctly

---

## Phase 4: Production Deployment

### ✅ Step 14: Production Readiness Checklist

**All previous steps completed:**
- [ ] Type verification passed (Step 2)
- [ ] SQLite migration successful (Step 5)
- [ ] SQLite schema verified (Step 6)
- [ ] SQLite application testing passed (Step 7)
- [ ] MSSQL backup completed (Step 8)
- [ ] MSSQL staging migration successful (Step 11)
- [ ] MSSQL staging schema verified (Step 12)
- [ ] MSSQL staging application testing passed (Step 13)

**Production environment ready:**
- [ ] Maintenance window scheduled
- [ ] Production database backed up (full + transaction log)
- [ ] Rollback plan documented
- [ ] Team notified of deployment
- [ ] config.ini MODE set to PRODUCTION

---

### ✅ Step 15: Apply Migrations to Production MSSQL

**During Maintenance Window:**

```bash
# 1. Verify MODE=PRODUCTION
grep "mode" code/config.ini

# 2. Check current migration status
alembic current

# 3. Apply migrations
alembic upgrade head

# 4. Verify migration status
alembic current
# Should show: 002_history_tables (head)
```

---

### ✅ Step 16: Verify Production Schema

Run the same verification queries as Step 12 on production database.

**Verification Results:**
- [ ] All columns exist with correct types
- [ ] All tables exist
- [ ] No unexpected schema changes

---

### ✅ Step 17: Post-Deployment Application Testing

```bash
# Start application
python3 -m uvicorn code.main:app --reload --port 8888

# Smoke tests
curl "http://localhost:8888/api/allocation-reports?month=April&year=2025"
curl "http://localhost:8888/api/history-log?page=1&limit=10"

# Check logs for errors
tail -f code/app.log
```

**Verification Results:**
- [ ] Application starts successfully
- [ ] All endpoints respond
- [ ] No type-related errors
- [ ] Data reads correctly
- [ ] No performance degradation

---

## Emergency Rollback Procedure

**If production deployment fails:**

### Option 1: Rollback Migrations

```bash
# Rollback to previous state
alembic downgrade -1  # Rollback one migration
# OR
alembic downgrade 001_initial  # Rollback to specific version
# OR
alembic downgrade base  # Rollback all migrations

# Verify rollback
alembic current
```

### Option 2: Restore from Backup

```sql
-- Stop application first!

-- Restore full backup
RESTORE DATABASE [YourDatabase]
FROM DISK = 'C:\Backups\YourDatabase_PreMigration_20260112.bak'
WITH REPLACE, RECOVERY;

-- Verify restore
SELECT @@SERVERNAME, DB_NAME(), GETDATE();
```

---

## Post-Deployment Monitoring

**Monitor for 24 hours after deployment:**

- [ ] Check application logs hourly for type-related errors
- [ ] Monitor database performance metrics
- [ ] Verify bench allocation operations complete successfully
- [ ] Verify history logging captures changes correctly
- [ ] Check for any unexpected NULL values in new columns

**Monitoring Commands:**
```bash
# Check recent errors
tail -n 500 code/app.log | grep -i "error\|exception\|type"

# Check recent history logs
curl "http://localhost:8888/api/history-log?page=1&limit=20"

# Check database locks/performance
# (MSSQL-specific queries)
```

---

## Sign-Off

**Deployment Completed By:**
- Name: ___________________
- Date: ___________________
- Environment: [ ] SQLite  [ ] MSSQL Staging  [ ] MSSQL Production

**Verification Sign-Off:**
- [ ] All checklist items completed
- [ ] All tests passed
- [ ] No errors in application logs
- [ ] Database schema verified
- [ ] Application functionality confirmed

**Notes:**
_______________________________________________________________
_______________________________________________________________
_______________________________________________________________

---

## Summary

This checklist ensures:
1. ✅ Type safety across SQLite and MSSQL
2. ✅ Data integrity (no data loss)
3. ✅ Transaction safety (automatic rollback on error)
4. ✅ Idempotent migrations (safe to run multiple times)
5. ✅ Proper testing before production deployment
6. ✅ Backup and rollback procedures in place

**Estimated Time:**
- Phase 1 (Type Safety): 10 minutes
- Phase 2 (SQLite Testing): 15 minutes
- Phase 3 (MSSQL Staging): 30 minutes
- Phase 4 (Production): 15 minutes
- **Total: ~70 minutes** (excluding backup time)

**Ready for Production Deployment!**
