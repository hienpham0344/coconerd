# Data schema

| Table | Purpose | Key invariants |
|---|---|---|
| `guild_settings` | Admin-enabled guilds/channels and retention | One row per guild; disabled by default |
| `messages` | Immutable Discord message snapshots | Unique `(guild_id, discord_message_id)` |
| `topics` | Guild-scoped topic lifecycle and thread mapping | Indexed by guild, state, and activity; version checked on processing updates |
| `conversation_episodes` | Separate periods of discussion for one topic | Guild and topic scoped |
| `message_topic_associations` | Topic, deferred, or irrelevant association evidence | One decision association per guild message |
| `topic_summaries` | Versioned structured memory and source IDs | Unique `(guild_id, topic_id, version)` |
| `topic_search_terms` | Local weighted lexical index of title/description/latest summary | PK `(topic_id, term)`; index `(guild_id, term)`; refreshed transactionally |
| `ai_decisions` | Auditable provider decision and model ID | Stores structured output, not provider credentials |
| `discord_actions` | Transactional outbox and action leases | Dependency, attempt count, lease owner/expiry, and Discord result IDs |
| `processing_jobs` | Durable message processing queue | Unique job per stored message; bounded attempts/lease, two call reservations, one reassessment |
| `model_configs` | Admin-only global and guild model settings | Provider, model ID, temperature, token ceiling |
| `worker_heartbeats` | Worker liveness | Last worker status timestamp |
| `review_events` | Moderator audit and idempotency | Unique guild/request ID; request fingerprint, actor label, reason, response, owning resource |
| `api_rate_limits` | Per-key minute-window counters | Stores key fingerprints, never raw API keys |

All application reads constrain by guild ID. Foreign keys are enabled in runtime SQLite connections. Alembic is the schema versioning mechanism; no startup `create_all()` is used.

## Evidence-agent migration

Revision `20261104_0002` adds the lexical index and job fields `model_call_count`, `reassessment_count`, `followup_message_id` (internal message record ID), `deferred_until`. It backfills terms from existing topics/latest summaries and conservatively initializes old call counts as `min(attempt_count, 2)`; this is not measured historical API usage. Existing messages and summaries are preserved.

Before running the new API/worker, back up any existing database, stop old processes and run `alembic upgrade head` from the repository using the intended environment. Downgrade removes the new index/fields.

**Historical deployment evidence, not a statement about the recovered checkout:** local deployment on 2026-11-04 was explicitly authorized by the user. The configured file `/home/hien/Project/coconerd/data/coconerd.db` did not exist, and no coconerd API/worker was running. Alembic initialized it through both revisions to `20261104_0002` (14 tables including `alembic_version`). There was no existing database to back up. Integrity and foreign-key checks passed; the new job columns and lexical index exist. The file is Git-ignored and has owner-only read/write permissions. Application-flow verification used a temporary SQLite backup copy; the configured database retains no synthetic messages/topics/jobs/actions.

Job states include `PENDING`, `CLAIMED`, `WAITING`, `SUCCEEDED`, `DEAD`. Expiring WAITING marks processing complete while its decision remains deferred. Only a `DEFERRED` message association can be changed automatically; `ai_decisions` retains both passes. Decision payloads include policy/model versions, actual candidate/context IDs, evidence, language hints and nullable usage.

## Retention and deletion

The recovered reliability checkout does not contain that historical runtime database; revision 0003 has only been exercised on disposable test databases.

Guild deletion removes review events, messages, decisions, associations, jobs, topics, search terms, episodes, summaries, actions, and settings. Topic deletion removes its associated messages and derived records, including search terms. Guild retention is configured per guild; the background worker enforces it every 15 minutes. It removes expired message bodies, processing jobs, associations, and decision payloads, and removes expired message IDs from summary provenance. Message source IDs remain in the version history until their source message expires. Retention does not rebuild historical summary text; terms derived from retained summaries can remain until the topic is updated or deleted.

## Reliability migration

Revision `20261104_0003` adds `topics.sync_paused`, `message_topic_associations.revision`, `discord_actions.superseded`, `discord_actions.lease_token` and `review_events`. Existing values default to false/1/false. It preserves source messages, old summary versions, retry/model counters and existing search terms while adding missing canonical phrase aliases. Review events follow guild/message/topic deletion and message retention; generic audit records do not hold API keys.

Correction increments association revision and affected topic versions, appends memory versions and preserves prior decisions. `MANUAL` associations cannot be overwritten automatically. `CANCELLED` means pending external work was superseded; attempted DEAD actions retain their original error but cannot recover after `superseded=true`. Paused topics still accept classified DB updates; resuming requires the latest version and explicit confirmation of external reconciliation.

Upgrade existing deployments only after backing up the intended SQLite file and stopping old processes. Run `alembic upgrade head` with API/worker pointed at the same database, then restart both. This change has not migrated a runtime database. Downgrade removes the new review state/audit table and therefore should not be used to preserve moderator history.
