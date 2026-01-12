# Fix: Duplicate Column Error

## Problem
```
sqlalchemy.exc.OperationalError: duplicate column name: BenchAllocationCompleted
```

This means the column already exists in your database, but Alembic doesn't know about it.

## Solution: Mark Migration as Applied

Since the columns already exist, just mark the migration as completed without running it:

```bash
# Mark migration as applied (without executing SQL)
alembic stamp head

# Verify
alembic current
```

This tells Alembic "these changes are already in the database, don't try to apply them again."

## Verify Columns Exist

Before stamping, verify the columns are actually there:

```bash
# Check AllocationExecutionModel columns
sqlite3 code/test.db "PRAGMA table_info(allocationexecutionmodel);" | grep -i "bench"

# Expected output:
# BenchAllocationCompleted|BOOLEAN|1||0
# BenchAllocationCompletedAt|DATETIME|0||
```

If columns exist with correct types, you're good to stamp!

## If Columns Are Missing or Wrong

If `BenchAllocationCompleted` exists but `BenchAllocationCompletedAt` doesn't:

```bash
# Add missing column manually
sqlite3 code/test.db "ALTER TABLE allocationexecutionmodel ADD COLUMN BenchAllocationCompletedAt DATETIME;"

# Then stamp
alembic stamp head
```

If `WorkHours` is still INTEGER instead of FLOAT:

```bash
# Check WorkHours type
sqlite3 code/test.db "PRAGMA table_info(monthconfigurationmodel);" | grep -i "workhours"

# If it shows INTEGER instead of FLOAT, you need to run the migration for that table
# But skip the BenchAllocationCompleted part
```

## Complete Fix Commands

```bash
# 1. Check what columns exist
echo "=== Checking AllocationExecutionModel ==="
sqlite3 code/test.db "PRAGMA table_info(allocationexecutionmodel);" | grep -i "bench"

echo "=== Checking MonthConfigurationModel ==="
sqlite3 code/test.db "PRAGMA table_info(monthconfigurationmodel);" | grep -i "workhours"

# 2. If both columns exist and WorkHours is FLOAT, just stamp
alembic stamp head

# 3. Verify
alembic current
# Should show: 001_initial (head)
```

## Why This Happened

Possible reasons:
1. You ran the migration partially before (it added BenchAllocationCompleted but failed after)
2. Columns were added manually via SQL
3. SQLModel auto-created the columns when you started the app
4. Migration was attempted multiple times

## After Stamping

Once stamped, future migrations will work normally:

```bash
# Check status
alembic current
# Output: 001_initial (head)

# Any new migrations will work
alembic upgrade head
```
