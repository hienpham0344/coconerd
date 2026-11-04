# Evidence-based Topic Classification Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. Continue the approved work inline.

**Goal:** Improve topic assignment evidence and recall with a durable cost bound.
**Architecture:** Local tools and versioned policy surround one Meta decision;
one later evidence-triggered reassessment is permitted. Existing UoW owns writes.
**Tech Stack:** Python 3.12, SQLite, SQLAlchemy, Alembic, LangGraph, pytest.
**Spec:** `docs/superpowers/specs/2026-11-04-evidence-topic-classification.md`

## Global Constraints

- Meta only; no bot setup or new dependency. Preserve original messages.
- Five cards, six context messages/1600 characters; two model calls per message.
- One reassessment within ten minutes; no cross-guild/channel clarification.
- No live DB migration or publishing. Paid evals require explicit bounded opt-in.

## Review Focus

- Invented evidence or an ID outside the actual shortlist cannot update memory.
- A topic older than the 30 most recent remains searchable; closed/foreign topics do not.
- Duplicate delivery or concurrent wakeup cannot schedule a third model call.
- Clarification arriving before the first decision must not be missed.
- Missing usage or predictions cannot silently improve evaluation scores.

### Task 1: Policy and structured evidence

Files: `application/contracts.py`, `application/decision_policy.py`, `application/agent_workflow.py`,
`infrastructure/meta_provider.py`, provider/policy tests.
- [x] Add failing tests for ambiguous acknowledgements, invented evidence, off-shortlist IDs, multi-topic input.
- [x] Add versioned instructions, schema fields and server validation; keep local blank handling.
- [x] Run focused tests; update mock and fixture evidence to the new contract.

### Task 2: Indexed retrieval and read-only tools

Files: topic search normalization/index, topic/summary repositories, ports/UoW,
`application/services/topic_tools.py`, context tests.
- [x] Test retrieval of old topics, accents/aliases, guild/status scope and index refresh.
- [x] Implement indexed lexical search and bounded context/evidence tools.
- [x] Integrate tools into message processing; reject title-only forced merges.

### Task 3: Durable budget and deferred reassessment

Files: models/migration, jobs/messages repositories, job ports, worker/budget wrapper.
- [x] Test one-shot wakeup, expiry, reply/author/channel scope, early arrival and failed-call budget.
- [x] Implement additive migration and backfill; lazy provider reserves calls durably.
- [x] Preserve old decisions; only a DEFERRED association can change automatically.
- [x] Verify disposable migrated DB and complete worker flow.

### Task 4: Evaluation and documentation

Files: `backend/agent_evaluation.py`, evaluation CLI/fixtures/tests, README and docs.
- [x] Add dev/holdout cases and metrics tests including missing predictions/usage.
- [x] Add bounded opt-in live runner; evaluate synthetic cases without presenting mock results as accuracy.
- [x] Update API/DB/workflow/config/run documentation.
- [x] Run full pytest, Ruff, migration smoke and diff checks; record observed limitations.

## Completion evidence — 2026-11-04

- Full suite: `.venv/bin/pytest -q --tb=short` → **177 passed, 2 warnings in 58.82s**. The warnings are Alembic's existing `path_separator` deprecation. Migration tests use disposable SQLite.
- Ruff check and format check across `backend tests scripts alembic` passed; `git diff --check` and changed-document link checks passed.
- Final focused regressions: **40 passed in 18.45s**. Reproduced then fixed early clarification pointing elsewhere, implicit clarification skipping a newer same-author message, closed-topic writes, followup ranking losing evidence, and stale index rows after explicit deletion.
- Three concurrent reservations produce exactly two successes in the disposable SQLite regression. This is not a high-load/multi-host lease-safety guarantee.
- Live dev runner: 3 Meta calls, 3 valid assignments matching provisional synthetic labels; 2 local decisions and 5 skipped rows after the cap. Holdout runner: 10 mock cases, zero paid calls. Reports and synthetic prediction snapshots are in `docs/evaluations/`; details and limitations in `docs/TESTING.md`.
- Inline final review covered evidence validation, actual shortlist IDs, guild/status scope, index lifecycle, early/late wakeup, call reservation persistence, error/skip denominators and output overwrite protection. No reviewer subagent was available through the current tools; no independent-review claim is made.

## Rulings and limits

- Ruling: if a same-author clarification has no explicit reply, do not skip a newer message or resolve equal-timestamp ambiguity — avoids linking one clarification to older pending messages, at the cost of leaving more ambiguous cases deferred.
- Ruling: use the same clarification-aware query in tool selection and workflow ranking — prevents the second rank pass from discarding the clarification while retaining the original target text.
- Ruling: keep CLI implementation in `backend.agent_evaluation_cli` with a thin script wrapper — works under the project's installed-package pytest invocation without adding a path hack.
- Ruling: retain prior language-normalization changes and their tests; do not overwrite unrelated concurrent work.
- Evidence validation checks references, not semantic truth. Lexical search still misses some paraphrases; up to 60 summary reads remain. Synthetic splits share templates and do not establish real-world accuracy or controlled token savings.
- Source workspace: `/home/hien/Project/coconerd`, branch `codex/evidence-topic-classification`. No live database migration, bot setup, commit or push in this increment.

## Authorized follow-up: local database initialization — 2026-11-04

The user subsequently requested applying the database changes, superseding the initial no-live-migration scope for this follow-up. Inspection found no database at the configured path and no running coconerd API/worker. Ran `alembic upgrade head` in `/home/hien/Project/coconerd`; the new `data/coconerd.db` is at `20261104_0002`, with integrity and foreign-key checks passing. No prior data existed to back up. Verified ingestion, duplicate delivery, mock worker classification, summary and outbox on a disposable backup copy of the initialized database; the configured database remains free of synthetic business data. See `docs/TESTING.md` for observed results. No bot setup or Git publication was performed.
