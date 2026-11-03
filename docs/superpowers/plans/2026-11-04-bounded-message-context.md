# Bounded Message Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each message classification a small, auditable set of relevant earlier messages without changing ingestion or persistence semantics.

**Architecture:** The message repository supplies scoped chronological reads. An application selector prioritizes the reply chain, then recent same-channel messages, under fixed size limits. The existing workflow passes these read-only objects to the Meta provider and persists selected IDs with the decision.

**Tech Stack:** Python 3.12, SQLAlchemy async/SQLite, LangGraph, FastAPI, Pydantic, pytest.

**Spec:** `docs/superpowers/specs/2026-11-04-bounded-message-context.md`

## Global Constraints

- Preserve the existing single-message HTTP contract and separate per-message jobs.
- No bot code, new dependency, database migration, extra model call, or live quality claim.
- Never include cross-guild, cross-channel, current, or future messages in context.
- Reply ancestry has priority; at most three ancestors, six total messages, 400 characters per item, 1,600 content characters overall, recent window ten minutes.
- Preserve pre-existing uncommitted work; do not stage, commit, or push.

## Review Focus

- A reply to an old message includes its ancestors while unrelated recent messages remain merely context.
- A message ingested late never sees later event-time messages.
- Cross-channel or cross-guild reply IDs are ignored.
- Blank messages and oversized content cannot bypass the prompt budget.
- Existing API and job behavior remains unchanged.

---

### Task 1: Scoped context selection

**Files:** `backend/application/read_models.py`, `backend/application/ports/persistence.py`, `backend/application/services/message_context.py`, `backend/infrastructure/database/repositories/messages.py`, `backend/infrastructure/database/unit_of_work.py`, `tests/backend/test_message_context.py`.

**Interfaces:** `MessagesRepository.recent_before(guild_id, channel_id, created_at, limit, after) -> Sequence[MessageReadModel]`; `build_message_context(messages_port, target) -> list[ContextMessage]`.

- [x] Write selector and repository tests for scope, time, reply priority, ordering, and budgets.
- [x] Run focused tests and observe failure.
- [x] Add the port, SQL read, plain context DTO, and selector.
- [x] Run focused tests and Ruff.

### Task 2: Workflow, provider, audit, and docs

**Files:** `backend/application/contracts.py`, `backend/application/agent_workflow.py`, `backend/application/services/messages.py`, `backend/infrastructure/meta_provider.py`, `tests/backend/test_meta_provider.py`, `tests/backend/test_processing.py`, `docs/AGENT_WORKFLOW.md`, `README.md`.

**Interfaces:** `ModelProvider.classify(message, candidates, context)`; workflow state contains `context: list[ContextMessage]`; decision payload contains `context_message_ids`.

- [x] Write failing tests for separate context JSON objects and persisted audit IDs.
- [x] Pass context through workflow and provider, update prompt and cache version.
- [x] Update user documentation for current behavior and limits.
- [x] Run focused tests, full suite, Ruff, formatting, and diff check.
