# PostgreSQL migration guide (v2.1+)

Obsidian Clan Bot currently uses **SQLite** (`data/obsidian_clanbot.db`) with `aiosqlite`. A future **v2.1** release may add optional PostgreSQL for hosts that need concurrent writes at scale (78+ guilds, heavy economy traffic).

This document is a **planning guide** — Postgres runtime support lands in **v2.1**. **v2.0.0-beta** adds `DB_BACKEND` / `DATABASE_URL` env vars and `core/db.py` guards only (SQLite remains default).

## When to consider Postgres

- Frequent `database is locked` errors under load (message economy + background tasks).
- Multiple bot replicas sharing one database (Railway horizontal scaling).
- Long-running analytics queries blocking command handlers.

SQLite remains fine for a **single bot process** and moderate guild count if WAL mode is on and writes are batched.

## Target architecture

1. **`DATABASE_URL`** — `postgresql://user:pass@host:5432/obsidian` (async: `postgresql+asyncpg://…` if using SQLAlchemy later).
2. **`DB_BACKEND`** — `sqlite` (default) or `postgres` (future).
3. **`core/db.py`** — single `open_db()` / connection pool abstraction; callers unchanged.
4. **Migrations** — versioned SQL files under `migrations/` applied on startup or via `python -m tools.migrate`.

## Schema porting notes

| SQLite pattern | Postgres equivalent |
|----------------|---------------------|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGSERIAL PRIMARY KEY` or `GENERATED ALWAYS AS IDENTITY` |
| `TEXT` timestamps (ISO) | `TIMESTAMPTZ` preferred for new columns |
| `ON CONFLICT … DO UPDATE` | Same syntax (UPSERT) |
| `datetime('now', '-5 minutes')` | `NOW() - INTERVAL '5 minutes'` |
| `INSERT OR IGNORE` | `ON CONFLICT DO NOTHING` |

Guild-scoped tables (`guild_id BIGINT`) should be indexed:

```sql
CREATE INDEX IF NOT EXISTS idx_command_usage_guild ON command_usage (guild_id, command_name);
CREATE INDEX IF NOT EXISTS idx_message_cooldowns ON message_cooldowns (guild_id, user_id);
```

## Migration steps (draft)

1. **Freeze schema** — export current SQLite DDL from `database/schema.py` / init scripts.
2. **Dual-write period (optional)** — write to both backends behind a feature flag; compare row counts nightly.
3. **Bulk copy** — `pgloader` or a one-off Python script:
   - Export SQLite tables to CSV.
   - Import with `COPY` into Postgres.
   - Reset sequences: `SELECT setval(pg_get_serial_sequence('table','id'), MAX(id)) FROM table;`
4. **Cutover** — set `DB_BACKEND=postgres`, restart bot, monitor `/admin health` and error logs.
5. **Rollback** — keep SQLite file snapshot for 7 days; flip `DB_BACKEND=sqlite` if needed.

## Environment (Railway)

```env
DB_BACKEND=postgres
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

Do **not** mount SQLite volume and Postgres at the same time without a clear primary.

## Code areas to touch (implementation checklist)

- `core/db.py` — pool + dialect-specific SQL helpers
- `database/__init__.py` — replace raw `aiosqlite.connect(DB_PATH)` gradually
- `tasks/_core.py`, `tasks/wf_check_loops.py` — high write frequency loops
- `handlers/message_economy.py` — per-message UPSERTs
- Health embed — show backend + pool stats

## Testing

- Run integration tests against Postgres in CI (Docker service).
- Load-test message economy + `record_command_usage` with 50 concurrent guilds.
- Verify WF notification dedup tables (`cycle_notifications_sent`, etc.) under parallel inserts.

## Timeline

| Phase | Scope |
|-------|--------|
| 2.0.x | SQLite only; document + index audit |
| 2.1-alpha | `open_db()` abstraction + Postgres driver |
| 2.1 | Migration tool + Railway template |

Questions or early adopters: note in deploy logs and test on a **staging guild** before production cutover.
