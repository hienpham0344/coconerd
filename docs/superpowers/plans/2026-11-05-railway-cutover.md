# Railway PostgreSQL Cutover Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Store all running bot/backend data in Railway PostgreSQL, including Discord delivery receipts, and preserve the existing SQLite history.

**Architecture:** Bring the existing PostgreSQL adapters from the sibling backend checkout into this monorepo without replacing its pending topic-delivery changes. The bot uses the authenticated backend HTTP API for receipt persistence. Runtime configuration rejects a SQLite fallback; SQLite remains available for isolated tests and the retained source backup.

**Tech Stack:** SQLAlchemy 2, asyncpg, Alembic, FastAPI, discord.py.

**Spec:** The user's explicit requirement in this chat: “tôi cần db là railway 100%”.

## Constraints and review focus

- Preserve existing uncommitted work, credentials, Discord IDs, and completed job/action states; do not commit or push.
- Read credentials only from existing ignored configuration, never print them.
- Copy data in one transaction; fail on conflicting destination records rather than overwrite them.
- Snapshot the source after stopping its writers. Keep SQLite files as backups.
- Do not replay completed Discord actions or send synthetic messages to real channels.
- A backend outage must fail receipt operations explicitly, never fall back to a local database.

## Tasks

- [x] Add and observe failing configuration/dialect and receipt API tests.
- [x] Integrate the already implemented PostgreSQL compatibility changes; enforce PostgreSQL when the runtime flag is enabled.
- [x] Add receipt repository/service/API and an additive migration; switch bot receipts to authenticated HTTP with retryable failures.
- [x] Verify transactional history import, conflict rejection, ID/state preservation, and repeat-import behavior using isolated databases.
- [x] Run focused and full backend/bot checks and migration/schema verification.
- [x] Stop existing SQLite writers, back up source/configuration, migrate and import into Railway, synchronize runtime configuration, restart API/worker/bot.
- [x] Verify live API health, bot connection, receipt writes, and Railway row counts; document the runtime command and recovery path.

## Execution ledger

- Initial diagnosis: bot/API/worker in this checkout use SQLite on port 8001; the sibling PostgreSQL API/worker use port 8000 with different keys. Railway business tables were created separately. Bot delivery receipts also use a local SQLite file.

- Verification: initial portability tests failed on PostgreSQL URL/index/dialect handling. New bot receipt and history-import tests were observed failing, then passing. Full suite before the separate receipt quota regression: 330 passed, 1 skipped; focused quota/auth/import checks after its fix: 17 passed. Ruff, formatting, compile and diff checks pass.
- Execution decision: preserve the existing dirty checkout and do not commit, per user instructions. Runtime cutover uses the monorepo on port 8000 and stops the older duplicate workers. All SQLite source files remain intact.
- Receipt recovery decision: recover IDs only from completed actions matching the saved thread. Mark a thread backfilled only when successful source-message IDs cover every associated source message; do not infer summary IDs whose recorded thread is unknown.

- Final verification: 331 passed, 1 PostgreSQL-only test skipped (no disposable PostgreSQL test server configured). Ruff, formatting, compile, diff and real-credential scans pass.
- Runtime cutover verified against actual Railway PostgreSQL: revision 20261105_0005; 15 messages, 1 topic, 9 summaries, 1 guild configuration, 18 actions, 15 jobs, 11 recovered receipts. All original business rows compared equal after import. Existing job states remain 13 SUCCEEDED and 2 DEAD.
- Actual HTTP receipt write/read was confirmed directly in Railway SQL and its unique verification row removed. API/database/worker health is ok; bot gateway is connected. API/worker/bot have no open local SQLite database handles.
- Canonical runtime: /home/hien/Project/discord-bot/coconerd, API http://127.0.0.1:8000. Runtime metadata, private logs and consistent SQLite snapshot: /tmp/coconerd-railway-cutover-_75n4okj. Both env files require PostgreSQL, share backend keys, and have mode 0600. No commit or push was performed.
