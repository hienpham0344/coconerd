# Data schema

| Table | Purpose | Key invariants |
|---|---|---|
| `guild_settings` | Admin-enabled guilds/channels and retention | One row per guild; disabled by default |
| `messages` | Immutable Discord message snapshots | Unique `(guild_id, discord_message_id)` |
| `topics` | Guild-scoped topic lifecycle and thread mapping | Indexed by guild, state, and activity; version checked on processing updates |
| `conversation_episodes` | Separate periods of discussion for one topic | Guild and topic scoped |
| `message_topic_associations` | Topic, deferred, or irrelevant association evidence | One decision association per guild message |
| `topic_summaries` | Versioned structured memory and source IDs | Unique `(guild_id, topic_id, version)` |
| `ai_decisions` | Auditable provider decision and model ID | Stores structured output, not provider credentials |
| `discord_actions` | Transactional outbox and action leases | Dependency, attempt count, lease owner/expiry, and Discord result IDs |
| `processing_jobs` | Durable message processing queue | Unique job per stored message; bounded attempts and lease |
| `model_configs` | Admin-only global and guild model settings | Provider, model ID, temperature, token ceiling |
| `worker_heartbeats` | Worker liveness | Last worker status timestamp |
| `api_rate_limits` | Per-key minute-window counters | Stores key fingerprints, never raw API keys |

All application reads constrain by guild ID. Foreign keys are enabled in runtime SQLite connections. Alembic is the schema versioning mechanism; no startup `create_all()` is used.

## Retention and deletion

Guild deletion removes messages, decisions, associations, jobs, topics, episodes, summaries, actions, and settings. Topic deletion removes its associated messages and derived records. Guild retention is configured per guild; the background worker enforces it every 15 minutes. It removes expired message bodies, processing jobs, associations, and decision payloads, and removes expired message IDs from summary provenance. Message source IDs remain in the version history until their source message expires.
