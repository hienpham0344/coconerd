# Backend architecture

## Runtime boundaries

- `backend/domain`: framework-free entities, enums, and lifecycle rules.
- `backend/application`: model-provider protocol, decision DTOs, model selection, and message-processing use cases.
- `backend/infrastructure`: SQLAlchemy persistence and the Meta Model API adapter.
- `backend/presentation/api`: authenticated HTTP contract for the independent Discord bot and administrators.
- `backend/worker.py`: separately launched durable message worker.

The Discord bot owns Discord SDK calls. It submits source messages, claims backend-created actions, executes those actions, and acknowledges results. The backend owns topic decisions, memory, persistence, authorization policy, and action ordering.

## Patterns in use

- **Repository:** isolates guild, message, topic, summary, job, and action persistence queries.
- **Unit of Work:** one SQLAlchemy session commits message/job ingestion together and commits processing decisions, memory, and outbox actions together.
- **Adapter / Protocol:** `ModelProvider` is the application port; `MetaModelProvider` and `MockMetaProvider` are adapters.
- **Selector:** `ModelSelector` applies an admin-set guild model override before the global model configuration.
- **Outbox:** Discord actions are stored in the same transaction as topic and summary changes.

SQLite is the current adapter. Domain decisions do not import FastAPI, Discord SDKs, or Meta SDKs. The Meta adapter uses the OpenAI-compatible Chat Completions API at the configured base URL.

## Reliability and security

Ingest inserts the message and processing job in one transaction with a unique `(guild_id, discord_message_id)` constraint. The worker claims jobs with expiring leases, bounded attempts, and backoff. Action claims have a separate lease and cannot bypass dependencies. API keys are compared in constant time; admin and bot credentials are separate; guilds must explicitly allow channels. Rate-limit keys are stored as SHA-256 fingerprints. Message text is not written to logs.

The worker moves inactive `ACTIVE` topics to `DORMANT` and closes their open episode after the configured inactivity window. It never infers `CLOSED` from inactivity; closing requires the admin endpoint.

SQLite migrations run with Alembic (`alembic upgrade head`). The API does not create or migrate tables at startup. Enable SQLite foreign-key enforcement in application connections. Use a single SQLite file on local storage; move to PostgreSQL before deploying multiple API/worker hosts that share remote storage.

## Limitations

- SQLite serializes writes; the worker claim algorithm is appropriate for the current local deployment scale, not a high-concurrency queue.
- Health reports the latest worker heartbeat, not whether every queued job is progressing.
- Live Meta behavior requires a valid Meta Model API key and account access; automated tests use the local mock.
