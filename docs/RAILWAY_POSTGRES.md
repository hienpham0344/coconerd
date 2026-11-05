# Railway PostgreSQL

API, worker, message history, guild configuration, summaries, outbox actions and
Discord delivery receipts use one Railway PostgreSQL database. The bot accesses
the backend over HTTP and does not receive database credentials.

Set the real connection URL only in ignored `.env`:

```dotenv
COCONERD_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@PUBLIC_HOST:PUBLIC_PORT/railway?ssl=require
COCONERD_REQUIRE_POSTGRES=true
COCONERD_HOST=127.0.0.1
COCONERD_PORT=8000
BACKEND_BASE_URL=http://127.0.0.1:8000
```

API and bot share `COCONERD_BOT_API_KEY`; setup uses the separate
`COCONERD_ADMIN_API_KEY`. The runtime flag rejects SQLite rather than silently
creating a local database. PostgreSQL being unavailable does not trigger a fallback.

From this checkout, use its Python interpreter for all entrypoints:

```bash
.venv/bin/python -m alembic upgrade head
.venv/bin/python -c 'from backend.presentation.api.cli import main; main()'
.venv/bin/python -m backend.worker
.venv/bin/python -m bot.main
```

Run API, worker and bot separately. Check `/api/v1/health`; `status`, `database`
and `worker` must all be `ok`. Avoid running a second worker from the old checkout.

## Transfer an existing SQLite history

Stop its bot, worker and API first and make a SQLite backup. Migration adds the
`delivery_receipts` table at revision `20261105_0005`. Use a stopped snapshot:

```bash
.venv/bin/python -m scripts.import_sqlite_history --source /absolute/path/backup.db
.venv/bin/python -m scripts.import_sqlite_history --source /absolute/path/backup.db --apply
```

If an old bot receipt database exists, add `--receipts /absolute/path/discord-delivery.db`.
The first command is read-only. Import preserves IDs, timestamps and completed
job/action states; an incompatible destination row rolls back the entire import.
Identical records can be imported again. Transient rate-limit counters and worker
heartbeats are recreated by the running services. SQLite backups are retained.

Before resuming delivery, recover known receipt mappings from completed actions
or an existing receipt database; verify topic history is already forwarded before
marking it backfilled. This prevents replaying history into an existing thread.

## Isolated tests

Runtime SQLite is disabled. Tests can explicitly use SQLite fixtures without
network or real Discord requests. A full PostgreSQL test run requires a separate
disposable test server via `COCONERD_TEST_POSTGRES_URL`; never point that variable
at Railway production.
