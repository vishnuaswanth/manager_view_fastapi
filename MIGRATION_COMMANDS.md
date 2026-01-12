# Quick Migration Commands Reference

## Check Migration Status

```bash
# Show current migration version
alembic current

# Show all migrations
alembic history

# Show pending migrations
alembic history --verbose
```

## Apply Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Apply one migration at a time
alembic upgrade +1

# Preview SQL without applying (dry-run)
alembic upgrade head --sql > migration.sql
```

## Rollback Migrations

```bash
# Rollback one migration
alembic downgrade -1

# Rollback to specific version
alembic downgrade <revision_id>

# Rollback all migrations (to base)
alembic downgrade base
```

## Mark Migration as Applied (Without Running)

```bash
# If you manually applied changes, mark migration as done
alembic stamp head

# Mark specific revision
alembic stamp <revision_id>
```

## For Your Current Migration

### Development (SQLite)

```bash
# 1. Backup database
cp code/test.db code/test.db.backup

# 2. Apply migration
alembic upgrade head

# 3. Verify
alembic current
sqlite3 code/test.db "PRAGMA table_info(allocationexecutionmodel);"
```

### Production (MSSQL)

```bash
# 1. BACKUP DATABASE FIRST (via MSSQL tools)

# 2. Set production mode in code/config.ini
# mode = PRODUCTION

# 3. Preview migration
alembic upgrade head --sql > migration_preview.sql
# Review the SQL file

# 4. Apply migration
alembic upgrade head

# 5. Verify
alembic current
```

## Emergency Rollback

```bash
# Quick rollback if something goes wrong
alembic downgrade -1

# Verify application still works
curl http://localhost:8888/api/allocation-reports
```

## Check What Changed

The migration adds these columns:
- `AllocationExecutionModel.BenchAllocationCompleted` (BOOLEAN, NOT NULL, default=False)
- `AllocationExecutionModel.BenchAllocationCompletedAt` (DATETIME, nullable)
- Changes `MonthConfigurationModel.WorkHours` from INTEGER to FLOAT

These changes are **safe** and **backward compatible**:
- Existing records get `BenchAllocationCompleted=False`
- Existing WorkHours values preserved (9 → 9.0)
- No data loss
