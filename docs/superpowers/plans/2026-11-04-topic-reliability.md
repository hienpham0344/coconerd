# Topic reliability implementation plan

> Execute inline with `superpowers:executing-plans`; use test-first regression checks and preserve the existing business boundaries.

**Goal:** Improve the concrete classification, memory and recovery failures found in the audit without growing a monolithic message service.

**Architecture:** Pure policy/reducer functions own decision and memory rules. Small application services orchestrate topic projection and corrections through existing persistence ports. SQL and lease fencing remain in infrastructure repositories.

**Tech stack:** Existing Python 3.12+, FastAPI, SQLAlchemy/SQLite, LangGraph and Meta adapter; no additional runtime dependency.

**Spec:** `docs/superpowers/specs/2026-11-04-topic-reliability.md`.

## Constraints and review focus

- Meta only; at most two reserved model attempts per message; no paid calls in verification.
- Preserve guild isolation, original text, version history, transaction/outbox atomicity and existing HTTP behavior except documented additions.
- Regress low-confidence valid-ID answers, same words/different projects, corrections to dates/tasks, stale worker completion, dead create-thread dependencies and cross-guild manual corrections.
- Work in the recovered clean checkout on `codex/topic-reliability`. Do not alter the stale chat worktree or create runtime DB data.

## Tasks

1. **Decision guard** — `decision_policy.py`, `contracts.py`, provider prompt/schema and policy tests. Write failing low-confidence new/existing tests, enforce a documented conservative floor, retain all evidence guards, bump policy/cache versions and verify targeted tests.
2. **Memory reducer/projection** — create `application/topic_memory.py` and `services/topic_projection.py`; simplify `services/messages.py`. Add structured, quoted replacements to the existing model response. Tests must prove old overview survives unrelated updates, explicit replacements remove superseded active facts without deleting historical versions, invalid replacements cannot mutate memory, and no-op updates create no summary action.
3. **Retrieval** — `topic_terms.py`, `topic_retriever.py`, `topic_tools.py`, summary repository/port. Test bilingual paraphrases and context anchors, latest memory card selection, unrelated-project separation and one batched summary fetch. Keep fixed candidate/context bounds.
4. **Durable execution** — job/action repositories, ports and worker services. Tests reproduce stale-owner complete/fail, expired final-attempt actions and failed dependencies. Fence writes, preserve retry budgets, and expose terminal outcomes rather than leaving misleading pending work.
5. **Manual review/correction** — add a focused application service and admin/message-status endpoints. Specify optimistic/idempotent correction behavior in the API contract before implementation; regress cross-guild access, repeated correction, summary/provenance rebuild and pending/performed Discord-action handling. Never mutate the original message snapshot or silently replay a performed side effect.
6. **Verification/documentation** — run all offline tests, Ruff lint/format, diff/architecture checks and any new migration tests. Update workflow/API/testing docs and the detailed backend readiness report, distinguishing deterministic tests from unmeasured Meta/Discord accuracy.

## Execution record

- Baseline recovered from remote commit `85aeb59`; no uncommitted user work in the recovered checkout.
- Audit-only verification before implementation: 16 unit tests passed, one graph test excluded in an isolated minimal environment; nine synthetic observations confirmed the policy/retrieval/memory behaviors. No Meta calls or database writes.
- Pending: fresh full-suite baseline in the project environment.

Commit/push from the earlier publication request has already produced the remote baseline. New reliability changes will be kept reviewable on their own branch; publication state must be reported separately from implementation/testing.
