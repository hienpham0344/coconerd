# Discord Conversation Organizer Backend Implementation Plan

> **For agentic workers:** Execute this plan task-by-task using the native Codex session. Keep each task testable; do not commit or push.

**Goal:** Build the backend described in the user-provided task attachment, without creating a new project or changing Discord bot code.

**Architecture:** Keep domain rules framework-independent, application use cases behind protocols, and FastAPI/SQLAlchemy/Meta Model API in infrastructure and presentation. Persist ingestion before AI work, and use database-backed jobs and outbox actions so restarts do not lose work.

**Tech Stack:** Python 3.12, FastAPI, Pydantic Settings, SQLAlchemy 2 async, SQLite, Alembic, LangGraph, pytest, HTTPX, Ruff.

**Spec:** `/home/hien/.codex/attachments/ae096d8b-96e2-4239-8a09-f152849452f4/Văn bản đã dán.txt`

## Global Constraints

- Do not create another project directory, implement a Discord bot, or modify `bot/`.
- Use SQLite and Alembic migrations; do not rely on production `create_all()`.
- Ingest idempotently and commit messages before AI processing.
- Use Meta Model API over its OpenAI-compatible endpoint; keep secrets in environment variables.
- Never claim live Meta API integration was tested without credentials; provide a deterministic offline mock.
- Do not commit, push, or create a PR.

## Review Focus

- Duplicate deliveries and worker restarts must not lose messages or duplicate actions.
- Lease expiry and action dependencies must prevent concurrent claims and premature APPEND_MESSAGE delivery.
- Cross-guild identifiers and reads must remain isolated.
- Uncertain or irrelevant model output must defer/ignore rather than force topic assignment.
- Meta API timeout, rate limit, invalid JSON, and auth failures must remain distinguishable and must not be reported as success.

## Implementation Tasks

1. [x] **Core setup and domain:** package, configuration, domain entities/state transitions, and domain tests.
2. [x] **Persistence and API contracts:** SQLAlchemy models, Alembic migration, repositories, idempotent ingestion, authentication, and topic/action endpoints.
3. [x] **Meta provider and agent workflow:** provider protocol/adapter, offline mock, structured decisions, candidate retrieval, summaries, and LangGraph routing.
4. [x] **Durable processing and outbox:** restart-safe jobs, retry/recovery, leased action claims, completion/failure, and dependencies.
5. [x] **Operations and documentation:** API/worker entry points, health checks, redacted logging, API/architecture/schema/workflow/model/testing docs, README, and prefixed backend environment settings.
6. [ ] **Verification:** Ruff and `git diff --check` pass. Focused offline tests passed earlier; DB-backed tests remain blocked by the reproduced SQLAlchemy/aiosqlite connection hang. Live Meta API was not tested because no credentials were provided.

## Decisions and Progress

- Bot setup remains out of scope. This implementation supplies backend APIs and an action outbox for the teammate's bot; it does not create, install, configure, or connect a Discord bot.
- The repository already had an unrelated `.env.example`; its existing values were preserved and backend settings use `COCONERD_*` names with legacy SQLite URL compatibility.
