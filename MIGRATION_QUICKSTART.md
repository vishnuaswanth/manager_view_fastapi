# Alembic Quick Start - Bench Allocation Migration

## 🚀 Quick Commands (Copy & Paste)

### 1. Install Alembic
```bash
pip3 install alembic
```

### 2. Generate Migration for Bench Allocation Fields
```bash
alembic revision --autogenerate -m "Add bench allocation tracking fields"
```

### 3. Apply Migration
```bash
alembic upgrade head
```

### 4. Verify Migration
**SQLite:**
```bash
sqlite3 code/test.db "PRAGMA table_info(allocationexecutionmodel);" | grep BenchAllocation
```

**MSSQL:**
```sql
SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'allocationexecutionmodel'
  AND COLUMN_NAME LIKE 'BenchAllocation%';
```

### 5. Start Your Application
```bash
python3 -m uvicorn code.main:app --reload
```

---

## ⚠️ If Migration Fails

**Rollback:**
```bash
alembic downgrade -1
```

**Check Status:**
```bash
alembic current
alembic history
```

---

## 📋 What Gets Added

The migration will add these columns to `allocationexecutionmodel`:

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| `BenchAllocationCompleted` | Boolean/Bit | NOT NULL | False |
| `BenchAllocationCompletedAt` | DateTime | NULL | NULL |

---

## 🔄 Complete Workflow

```bash
# 1. Install (one-time)
pip3 install alembic

# 2. Generate migration
alembic revision --autogenerate -m "Add bench allocation tracking fields"

# 3. Review the generated file in alembic/versions/

# 4. Apply migration
alembic upgrade head

# 5. Verify columns exist
sqlite3 code/test.db "PRAGMA table_info(allocationexecutionmodel);"

# 6. Start application
python3 -m uvicorn code.main:app --reload
```

---

## 📖 For More Details

See **ALEMBIC_GUIDE.md** for complete documentation including:
- Troubleshooting
- Best practices
- Production deployment
- Rollback strategies
- Advanced usage

---

## ✅ Success Indicators

You'll know migration succeeded when you see:
```
INFO  [alembic.runtime.migration] Running upgrade  -> abc123, Add bench allocation tracking fields
```

And your application starts without errors related to `BenchAllocationCompleted` or `BenchAllocationCompletedAt`.
