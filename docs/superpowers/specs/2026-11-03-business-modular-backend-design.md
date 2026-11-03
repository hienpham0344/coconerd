# Business Modular Backend Design

## Intent

Organize the backend around the product's business capabilities so API handlers stay small, business rules can be found in one place, and persistence details do not leak into HTTP code. The current backend already has domain/application/infrastructure/presentation folders, but `presentation/api/app.py` combines all route definitions and several use cases, while `application/services.py` combines message ingestion, topic classification, memory updates, and job completion.

## Goals

- Make each API route module correspond to a business capability: messages, topics, actions, guild administration, model configuration, or health.
- Keep HTTP handlers responsible for request/response translation and HTTP status mapping.
- Move use-case rules and transactions into application services grouped by capability.
- Move SQLAlchemy reads/writes out of HTTP handlers, worker scheduling code, and application use cases into repositories.
- Split persistence repositories by business aggregate while keeping SQLAlchemy record definitions centralized initially.
- Keep a single deployable backend, one API process, one worker, and the existing SQLite database.
- Preserve existing classification work in the uncommitted working tree.

## Non-goals

- No Discord SDK or bot setup.
- No new API endpoints, renamed paths, changed request/response contracts, or behavior changes.
- No database engine, table, migration, or schema changes.
- No microservices, message broker, event bus, or dependency-injection framework.
- No new third-party dependencies.

## Constraints

- Maintain `/api/v1` paths, auth headers, response codes, validation, retry and outbox semantics.
- Keep domain rules independent of FastAPI and SQLAlchemy.
- Keep FastAPI dependency wiring at the presentation boundary and SQLAlchemy queries inside infrastructure repositories.
- Preserve current uncommitted changes; do not stage, commit, or push as part of this refactor.
- Keep API and worker entrypoints operational with the same environment variables.

## Approaches considered

1. **Split only the route file.** Move endpoints into router modules while keeping database and business logic in handlers. This is a low-risk first step, but it leaves business rules hard to locate and test independently.
2. **Business modular monolith (chosen).** Split routes, use cases, and repositories by business capability, while preserving the existing domain, database models, API composition root, and deployment shape. This addresses both file size and separation of responsibilities without creating distributed-system complexity.
3. **Full DDD or microservices.** Add separate deployables, domain event infrastructure, and more formal aggregate boundaries. That is disproportionate for the current single-host SQLite backend and would add migration/operational risk without a stated scale requirement.

## Proposed boundaries

```text
backend/
  domain/                         # framework-independent entities and rules
  application/
    services/
      messages.py                 # ingest and process message use cases
      topics.py                   # read, close, and delete topic use cases
      health.py                   # database/worker health use case
      actions.py                  # claim, complete, and fail actions
      guilds.py                   # guild settings and data retention/delete use cases
      model_config.py             # global/guild model configuration use cases
      jobs.py                     # durable worker job state transitions and heartbeat use cases
      retention.py                # retention cleanup and topic dormancy use cases
    agent_workflow.py             # classification orchestration
    contracts.py                  # provider/result DTOs and ports
  infrastructure/
    database/
      repositories/
        messages.py
        topics.py
        actions.py
        guilds.py
        health.py
        jobs.py
        model_config.py
        retention.py
        summaries.py
      models.py                   # existing table mappings; unchanged in this scope
    meta_provider.py
  presentation/
    api/
      app.py                      # composition root, middleware, shared dependencies
      routers/
        health.py
        messages.py
        topics.py
        actions.py
        guilds.py
        model_config.py
      schemas.py
      security.py
      rate_limit.py
  worker.py                       # worker composition root
```

Feature routers receive explicit dependencies (unit of work, settings, auth) and call application use cases. Application services own validation that is business-specific, transaction coordination, and error types. Infrastructure repositories own SQL queries and ORM mapping; application services use persistence ports and plain domain/DTO data, not SQLAlchemy models or statements. The worker remains a composition/scheduling entrypoint; job claiming/completion, model-config lookup, heartbeat, retention, and dormancy work move behind application use cases and repositories. `create_app()` only composes routers, middleware, lifespan, and shared dependencies. Existing domain entities and SQLAlchemy mappings stay centralized to avoid a speculative schema/domain rewrite.

## Error and transaction behavior

- Application services raise typed business errors such as `ChannelNotAllowedError`, not `HTTPException`.
- Routers map those errors to the same current HTTP status and response shape.
- An application Unit of Work owns session lifetime and commits at the same point as today; APIs and the worker no longer issue ad hoc commits for business use cases.
- The classification use case keeps its current single transaction for topic/association/decision/summary/outbox writes, while provider calls remain outside write transactions where they are today.
- Database cascades, guild scoping, topic lifecycle checks, worker leases, and outbox dependency ordering remain unchanged.

## Verification

- Assert the current routes, auth requirements, response shapes, and status codes through FastAPI/OpenAPI tests.
- Preserve test coverage for guild isolation, topic lifecycle, action idempotency/retry, and offline processing.
- Run focused tests after each business slice, then Ruff and the full suite.
- Do not claim successful end-to-end verification if the existing LangGraph `ainvoke()` hang persists; record it separately from structural changes.
