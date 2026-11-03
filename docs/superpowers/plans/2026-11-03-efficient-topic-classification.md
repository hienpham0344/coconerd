# Efficient Topic Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Reduce irrelevant model context and enforce reliable decision shape while keeping all model calls on Meta Model API.

**Architecture:** A bounded local retriever ranks up to 30 same-guild candidate topics and passes at most five compact topic cards to the existing Meta classifier. Meta returns a JSON-Schema-constrained decision; application validation remains authoritative. Stable prompt prefixes enable Meta's automatic prefix cache, and usage telemetry records actual cached tokens rather than estimating savings.

**Tech Stack:** Python 3.12, Pydantic, SQLAlchemy async, LangGraph, OpenAI-compatible Meta Chat Completions, SQLite, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-11-03-efficient-topic-classification-design.md`

## Global Constraints

- Keep all model calls on Meta Model API; do not add another provider or API key.
- The local retriever may shortlist but cannot assign topics or write persistence records.
- Preserve `new`, `existing`, `defer`, and `irrelevant` outcomes and durable job/outbox behavior.
- Scope retrieval to the current guild and exclude closed topics.
- Keep message text out of logs and do not treat self-reported confidence as calibrated.
- Do not claim measured accuracy or token savings without labeled evaluation and provider usage data.

## Review Focus

- A relevant topic outside the top five must remain measurable as a retrieval miss; test Recall@5 on hand-labeled fixture predictions.
- Cross-guild or closed topics must never be candidates; assert candidate IDs are guild-scoped and lifecycle-filtered.
- Prompt-cache usage fields may be absent; preserve `null`/unknown rather than report false savings.
- Structured output can contain invalid topic IDs despite schema-valid JSON; validate and defer instead of associating another topic.
- Empty/irrelevant messages, direct replies, duplicate titles, weak lexical overlap, and Unicode/Vietnamese text must follow stable routing behavior.

---

### Task 1: Structured classification contracts and Meta usage

**Files:**
- Modify: `backend/application/contracts.py`
- Modify: `backend/infrastructure/meta_provider.py`
- Modify: `backend/application/agent_workflow.py`
- Modify: `backend/application/services.py`
- Create: `tests/backend/test_meta_provider.py`
- Modify: `tests/backend/test_processing.py`

**Interfaces:**
- Add `ClassificationResult(decision: TopicDecision, model_id: str, prompt_tokens: int | None, completion_tokens: int | None, cached_tokens: int | None, latency_ms: int)` in application contracts.
- Change `ModelProvider.classify(message, candidates) -> ClassificationResult`; `MockMetaProvider` returns the same contract with usage fields set to `None`.
- Store usage and model ID in `AIDecisionRecord.payload`; do not create a migration just for telemetry.

- [ ] Write `test_meta_provider_requests_strict_topic_decision_schema` and `test_meta_provider_records_usage_with_and_without_cached_tokens` using a fake OpenAI-compatible client.
- [ ] Run `pytest tests/backend/test_meta_provider.py -q`; expected: the new tests fail because the provider still sends JSON mode and exposes no usage result.
- [ ] Define `ClassificationResult` and optional `ProviderUsage`; return the result through LangGraph while passing only its validated decision to persistence.
- [ ] Define strict `TopicDecision` JSON Schema: all properties required, `topic_id`/`title` nullable, enum outcomes, bounded confidence/lists, and `additionalProperties: false`; send `response_format.type=json_schema`, `strict: true`.
- [ ] Parse/validate output; map refusal, empty output, invalid schema, and provider failures to explicit errors. Capture token counts, cached tokens when present, and elapsed time without logging message text.
- [ ] Run `pytest tests/backend/test_meta_provider.py tests/backend/test_processing.py -q`; expected: focused provider and processing tests pass.

### Task 2: Local topic retrieval and compact context

**Files:**
- Create: `backend/application/topic_retriever.py`
- Modify: `backend/application/agent_workflow.py`
- Modify: `backend/application/services.py`
- Modify: `backend/application/contracts.py`
- Create: `tests/backend/test_topic_retriever.py`

**Interfaces:**
- `retrieve_topic_candidates(message: ConversationMessage, candidates: list[TopicCandidate], limit: int = 5) -> list[TopicCandidate]`
- Search only the existing bounded candidate list (maximum 30) loaded by `TopicRepository`; never query outside the message guild.
- Preserve a stored direct-reply target at the head of the shortlist and its `direct_reply_target` evidence.

- [ ] Write tests `test_retriever_ranks_title_above_summary_matches`, `test_retriever_keeps_direct_reply_first`, `test_retriever_uses_recent_fallback_for_zero_overlap`, and `test_retriever_handles_unicode_and_candidate_limit`.
- [ ] Run `pytest tests/backend/test_topic_retriever.py -q`; expected: tests fail because the retriever does not exist.
- [ ] Implement `retrieve_topic_candidates(message, candidates, limit=5)` using case-folded Unicode word tokens and deterministic scoring: per unique message token, use the highest match weight (title 3, description 1.5, summary 0.75), sum, divide by `3 * unique_message_tokens`.
- [ ] Keep a direct-reply candidate first and fill remaining slots by score; on zero overlap return at most five recent topics and instruct the main model to prefer `new` or `defer` over unsupported matches.
- [ ] Compact cards to title (120 chars), description (240), summary overview (400), at most three items per summary list (120 chars each), preserving reply evidence.
- [ ] Insert a LangGraph retrieval node before classification; keep existing guild/lifecycle/invalid-ID checks authoritative.
- [ ] Add Recall@5 to `backend/evaluation.py`; run `pytest tests/backend/test_topic_retriever.py -q` and expect all retrieval cases to pass.

### Task 3: Stable prompt prefix, context, and telemetry persistence

**Files:**
- Modify: `backend/infrastructure/meta_provider.py`
- Modify: `backend/application/services.py`
- Modify: `docs/AGENT_WORKFLOW.md`
- Modify: `docs/MODEL_CONFIGURATION.md`
- Modify: `tests/backend/test_meta_provider.py`

- [ ] Write `test_meta_provider_uses_stable_cache_key_and_prefix_order` and `test_processing_persists_optional_usage_metrics`.
- [ ] Run the two tests; expected: fail because current requests have no cache key/usage telemetry.
- [ ] Keep versioned stable system instructions and JSON Schema before per-message context; place volatile message/topic cards last.
- [ ] Set one stable `prompt_cache_key` for the shared classification prefix; never key by guild or message.
- [ ] Persist prompt/completion/cached-token counts, model ID, stage, and latency; absent details stay unknown, not zero.
- [ ] Document provider-managed caching and cached-token ratio; run `pytest tests/backend/test_meta_provider.py tests/backend/test_processing.py -q`; expect focused tests to pass.

### Task 4: Evaluation contract and final verification

**Files:**
- Modify: `scripts/evaluate_grouping.py`
- Modify: `backend/evaluation.py`
- Modify: `docs/TESTING.md`
- Modify: `README.md`
- Test: `tests/backend/test_evaluation.py`

- [ ] Write `test_candidate_recall_at_5_counts_retrieved_gold_topics` and `test_candidate_recall_at_5_handles_messages_without_gold_topics` using hand-authored predictions.
- [ ] Run `pytest tests/backend/test_evaluation.py -q`; expected: Recall@5 tests fail because the metric is absent.
- [ ] Extend prediction JSONL with `candidate_topic_ids`; report Recall@5 with pairwise precision/recall/F1 and reject malformed IDs.
- [ ] Clarify that the synthetic fixture only exercises tooling; accuracy needs representative labeled conversations.
- [ ] Run focused tests, Ruff, and link/diff checks; report DB integration limitations and do not claim live Meta or benchmark verification without evidence.
