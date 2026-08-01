# PostgreSQL Migration Guide

Switch BenchmarkOps from the default SQLite database to PostgreSQL 14+ for production use.

---

## 1. Prerequisites

- **PostgreSQL 14 or later** installed and running.
  - Windows: [PostgreSQL Installer](https://www.postgresql.org/download/windows/)
  - macOS: `brew install postgresql@16`
  - Linux: `sudo apt install postgresql-16`
- A database and user created:

```sql
CREATE USER benchmarkops WITH PASSWORD 'secure_password';
CREATE DATABASE benchmarkops OWNER benchmarkops;
GRANT ALL PRIVILEGES ON DATABASE benchmarkops TO benchmarkops;
```

## 2. Configuration

Edit `backend/.env` (or copy `.env.example` → `.env`) and replace the SQLite URL with a PostgreSQL connection string:

```env
DATABASE_URL=postgresql+asyncpg://benchmarkops:secure_password@localhost:5432/benchmarkops
```

Install the async driver if not already present:

```bash
cd backend
pip install asyncpg
```

Restart the backend after changing `.env`.

## 3. Data Migration (SQLite → PostgreSQL)

Run the included migration script to export all data from the current SQLite database and import it into PostgreSQL:

```bash
cd backend
python scripts/migrate_to_postgres.py
```

The script reads from the existing SQLite file (`benchmarkops.db`), connects to the target PostgreSQL instance, and copies every table row-by-row. It reports per-table success/failure counts.

> **Tip:** Back up your SQLite database before running the migration.

## 4. Verification

After the migration completes:

1. **Start the backend** pointing at PostgreSQL and check health:

   ```bash
   cd backend
   uvicorn app.main:app --port 8000
   curl http://localhost:8000/api/v1/health
   ```

2. **Count tables** in PostgreSQL:

   ```sql
   SELECT count(*) FROM information_schema.tables
   WHERE table_schema = 'public';
   ```

   You should see the same number of tables as existed in SQLite (typically 8–10).

3. **Spot-check row counts** against your old SQLite file:

   ```sql
   -- SQLite side
   sqlite3 benchmarkops.db "SELECT name, (SELECT count(*) FROM sqlite_master WHERE type='table') FROM projects;"

   -- PostgreSQL side
   SELECT count(*) FROM projects;
   ```

## 5. Rollback

To switch back to SQLite:

1. Edit `backend/.env` and restore the SQLite URL:

   ```env
   DATABASE_URL=sqlite+aiosqlite:///./benchmarkops.db
   ```

2. Restart the backend. Your original SQLite database is untouched — all writes go back to it.

If you need to move data back from PostgreSQL to SQLite, run the same script with roles reversed (see the script's `--reverse` flag):

```bash
python scripts/migrate_to_postgres.py --reverse
```
