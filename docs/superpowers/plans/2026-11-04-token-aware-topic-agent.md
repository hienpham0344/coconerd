# Token-aware Topic Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Reduce avoidable Meta calls and measure reasoning-token cost without adding model subagents or a new retrieval store.

**Architecture:** Keep the local retrieval/context nodes and one Meta decision. A local blank-text rule bypasses the provider. The provider uses configurable reasoning effort and records structured usage, including a distinct truncation error.

**Tech Stack:** Python 3.12, Pydantic Settings, LangGraph, OpenAI-compatible Meta Model API, pytest.

**Spec:** `docs/superpowers/specs/2026-11-04-token-aware-topic-agent.md`

## Global Constraints

- Preserve Meta-only operation, one-message HTTP contract, JSON Schema decision and transactional persistence.
- No bot work, new provider, dependency, migration, vector database, or extra model call.
- Never log or commit credentials or raw Discord message content.
- A few synthetic examples do not establish classification accuracy or token savings.

## Review Focus

- Missing reasoning usage remains unknown; a local rule records known zero usage.
- Empty strings and whitespace-only strings avoid the provider; nonempty short replies still use it.
- `finish_reason=length` is reported distinctly even if the content is empty or partial.
- Settings reject unsupported reasoning-effort values before a paid call.
- Existing guild/channel scope and outbox behavior stay unchanged.

---

### Task 1: Provider cost control and telemetry

**Files:** `backend/config.py`, `backend/application/contracts.py`, `backend/infrastructure/meta_provider.py`, `backend/application/services/messages.py`, `.env.example`, `tests/backend/test_meta_provider.py`.

**Interfaces:** `Settings.llm_reasoning_effort`; `ClassificationResult.reasoning_tokens`; `MetaOutputTruncatedError`.

- [x] Add failing tests for effort, reasoning usage, truncation and invalid effort.
- [x] Run focused tests and observe expected failures.
- [x] Add the setting, Meta request parameter, usage parsing and explicit truncation error.
- [x] Run focused tests and Ruff.

### Task 2: Local blank-text policy and documentation

**Files:** `backend/application/agent_workflow.py`, `tests/backend/test_processing.py`, `docs/AGENT_WORKFLOW.md`, `docs/MODEL_CONFIGURATION.md`.

**Interfaces:** A blank message produces `ClassificationResult` with `irrelevant`, `model_id=local-empty`, and known zero token usage; no provider call.

- [x] Add a failing workflow/service test with a provider that rejects calls.
- [x] Implement the local rule without changing nonblank classification.
- [x] Document the cost control and RAG/subagent decision gate.
- [x] Run focused tests, full suite, Ruff, formatting and diff checks.

### Task 3: Live check when the user supplies a Meta key

**Files:** None.

- [x] Verify `COCONERD_MODEL_API_KEY` is present without printing it.
- [x] Run bounded synthetic `new`, `existing reply`, and ambiguous short-text cases, recording outcomes and provider token/latency counts.
- [x] Report observed results and limitations; do not claim representative accuracy.

## Review adjustment and evidence

- Output truncation now stops automatic retries with `DEAD`; the original message remains stored. This avoids repeating a paid request with an exhausted budget. Temporary errors retain bounded retries.
- Regression tests cover the persisted failure, released lease, retained message, and worker mapping for truncation versus timeout.
- Live results and the `irrelevant` versus `defer` limitation are recorded in `docs/TESTING.md`. No further paid calls are needed for this increment.
