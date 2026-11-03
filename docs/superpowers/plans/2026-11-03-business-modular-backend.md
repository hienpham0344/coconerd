# Business Modular Backend Refactor Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax.

**Goal:** Reorganize the backend into business-focused modules with thin HTTP/worker entrypoints and persistence isolated behind repositories, without changing API or data behavior.

**Architecture:** Keep one modular-monolith deployment and the existing framework-independent domain. Introduce application persistence ports and a SQLAlchemy Unit of Work, then group use cases, repositories, and API routers by messages, topics, actions, guild administration, and model configuration. Keep `create_app()` and `worker.py` as composition/scheduling entrypoints.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy async, SQLite/Alembic, LangGraph, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-11-03-business-modular-backend-design.md`

## Global Constraints

- Preserve all `/api/v1` paths, auth headers, status codes, response shapes, validation, retry behavior, and outbox ordering.
- Do not set up Discord bot integration or change database tables, migration history, or the SQLite engine.
- Keep SQLAlchemy queries and ORM mappings in `backend/infrastructure/database`; application services depend on persistence ports and plain DTOs.
- Keep `create_app()` limited to composition, middleware, lifespan, and shared dependencies; keep `worker.py` limited to process lifecycle and scheduling.
- Preserve every existing uncommitted classification, retrieval, telemetry, test, README, and design/plan change. Do not stage, commit, or push without a specific request for this refactor.
- Preserve current transaction boundaries and ensure provider calls do not hold write transactions open.

## Review Focus

- Existing route/auth/status/response contracts remain byte-for-byte equivalent where practical; verify with OpenAPI and API tests.
- Cross-guild isolation and closed-topic checks remain enforced in the application use case, not only by router parameters.
- Action completion is idempotent only for matching results; mismatched worker leases still return conflict.
- Classification writes (topic, episode, association, decision, summary, outbox actions) remain in one transaction; provider calls remain outside the write transaction.
- Worker retries, leases, retention cleanup, and topic dormancy preserve existing timing and state transitions.

---

### Task 1: Persistence ports and Unit of Work

**Files:**
- Create: `backend/application/ports/persistence.py`
- Create: `backend/infrastructure/database/unit_of_work.py`
- Split: `backend/infrastructure/database/repositories.py` into `backend/infrastructure/database/repositories/`, including `__init__.py`
- Modify: `backend/presentation/api/app.py`, `backend/worker.py`, `tests/backend/conftest.py`
- Test: focused repository and Unit of Work tests

**Interfaces:**
- `UnitOfWork` exposes repositories grouped by `messages`, `topics`, `actions`, `guilds`, `health`, `model_config`, `jobs`, `summaries`, and `retention`, plus `commit()` and `rollback()`.
- Repository protocols return application read models/domain objects and raise no HTTP exceptions.
- `SqlAlchemyUnitOfWork` adapts the existing `AsyncSession`; repository methods own all SQL statements and ORM mapping.

- [x] Add unit tests for Unit of Work commit/rollback and repository behavior that currently has no focused coverage.
- [x] Run focused tests and record current behavior before relocating implementation.
- [x] Move repository classes by business aggregate, retaining their existing query ordering, filters, lease rules, and public method behavior.
- [x] Implement the Unit of Work adapter and application ports; keep migrations and `models.py` unchanged.
- [x] Update application composition to construct the Unit of Work at the API/worker boundary.
- [x] Run focused repository tests and Ruff.

### Task 2: Message ingestion and classification use cases

**Files:**
- Create: `backend/application/services/messages.py`
- `messages.py` contains ingestion and message classification/summary processing; topic reads/admin lifecycle stay in `topics.py` from Task 3.
- Create: `backend/application/services/jobs.py`
- Create: `backend/application/services/results.py`
- Create: `backend/application/errors.py`
- Modify: `backend/application/services.py` (remove after callers migrate)
- Modify: `backend/worker.py`, `backend/presentation/api/app.py` (temporary existing route caller)
- Modify: `tests/backend/test_api.py`, `tests/backend/test_processing.py`, `tests/backend/test_meta_provider.py`

**Interfaces:**
- `IngestResult(message_id: str, inserted: bool)`
- `ProcessingResult(outcome: str, topic_id: str | None, candidate_topic_ids: list[str])`
- `ingest_message(uow: UnitOfWork, message: ConversationMessage, max_attempts: int) -> IngestResult`
- `process_message_record(uow: UnitOfWork, message_record_id: str, provider: ModelProvider) -> ProcessingResult`
- `complete_job(uow: UnitOfWork, job_id: str) -> None`
- Application services use the persistence ports only; classification output and candidate IDs stay in the decision payload.

- [x] Add/adjust tests for channel allowlisting, deduplication, shortlist recording, topic/episode/association/summary/action writes, and processing atomicity.
- [x] Extract ingestion and processing into separate use cases without changing behavior or commit boundaries.
- [x] Move all classification reads/writes and summary/outbox persistence behind repositories; map ORM records to DTOs at repository boundaries.
- [x] Keep the provider call between read preparation and write transaction, matching current behavior.
- [x] Remove the old shared `application/services.py` imports after API and worker callers migrate.
- [x] Run processing tests; if LangGraph `ainvoke()` still hangs in the current environment, record the exact failure and continue with tests that do not depend on it.

### Task 3: Topic, action, guild, and model-configuration use cases

**Files:**
- Create: `backend/application/services/topics.py`
- Create: `backend/application/services/health.py`
- Create: `backend/application/services/actions.py`
- Create: `backend/application/services/guilds.py`
- Create: `backend/application/services/model_config.py`
- Modify: `backend/infrastructure/database/repositories/` modules
- Modify: `tests/backend/test_api.py` and focused service tests

**Interfaces:**
- Each service accepts a `UnitOfWork` and business parameters; it returns domain entities or response-independent DTOs.
- Business failures use typed application exceptions (`NotFound`, `Conflict`, `InvalidTransition`, `ChannelNotAllowed`) for presentation mapping.

- [x] Add tests for guild settings, guild data deletion, model-config fallback/override, topic read/close/delete, and action claim/complete/fail.
- [x] Move the corresponding SQL and state-transition rules from API handlers into use cases and repositories.
- [x] Preserve guild scoping, action lease ownership/idempotency, response semantics, retention constraints, and transaction boundaries.
- [x] Run focused service/API tests and Ruff.

### Task 4: Business-focused API routers and composition root

**Files:**
- Create: `backend/presentation/api/routers/{health,messages,topics,actions,guilds,model_config}.py`
- Modify: `backend/presentation/api/app.py`
- Keep: `backend/presentation/api/{schemas.py,security.py,rate_limit.py}` unless a clear shared-boundary issue is found
- Modify: `tests/backend/test_api.py`

- [x] Add OpenAPI/API contract assertions for paths, methods, auth dependencies, status codes, and schemas.
- [x] Move routes into routers by business capability; handlers validate transport input, call use cases, and map application exceptions to the same HTTP responses.
- [x] Reduce `create_app()` to middleware, shared dependency construction, lifespan, and `include_router()` calls.
- [x] Verify all existing API tests and compare generated route inventory with the pre-refactor contract.

### Task 5: Worker use cases and composition boundary

**Files:**
- Create: `backend/application/services/retention.py`
- Create/modify: `backend/application/services/jobs.py`, `backend/application/services/model_config.py`, `backend/application/services/topics.py`
- Create: `backend/infrastructure/database/repositories/retention.py` and any required heartbeat/model-config repository
- Modify: `backend/worker.py`
- Test: worker/job/retention lifecycle tests

- [x] Add tests for heartbeat upsert, provider selection, failed-job retry/dead-letter transition, retained-message pruning, action payload redaction, and `ACTIVE` to `DORMANT` episode closure.
- [x] Move all SQL/model mutations in worker scheduling helpers to use cases and repositories.
- [x] Keep worker polling, graceful stop, provider lifecycle, and timer scheduling in `ConversationWorker`.
- [x] Verify worker tests plus API/use-case suites.

### Task 6: Documentation and final verification

**Files:**
- Modify: `docs/BACKEND_ARCHITECTURE.md`, `docs/AGENT_WORKFLOW.md`, `README.md`, `docs/TESTING.md`
- Verify: API OpenAPI, focused tests, Ruff, `git diff --check`

- [x] Document the business-module layout, dependency direction, transaction ownership, API/worker startup, and unchanged SQLite storage path.
- [x] Search for raw SQLAlchemy statements in API routers/application services/worker and confirm remaining occurrences are only infrastructure or composition wiring.
- [x] Run focused tests, API contract tests, Ruff, and `git diff --check`; run the full suite if the environment permits.
- [x] Report any remaining LangGraph runtime blocker separately and make no unverified accuracy or runtime claims.
