# Efficient Topic Classification Design

## Intent

Improve topic assignment quality while reducing how much conversation context reaches the main model. The user proposed a lightweight retrieval agent with a stronger final decision; the selected Meta-only setup implements that first stage as a deterministic local LangGraph node so it does not add a second provider/key or model call.

## Goals

- Return validated, machine-readable decisions using a strict JSON Schema.
- Keep candidate retrieval guild-scoped and bounded; never let a lightweight stage assign a topic directly.
- Use local retrieval to shortlist topics; keep all model calls on Meta Model API in this scope.
- Give the main classifier a compact shortlist and topic memories, then let it choose `new`, `existing`, `defer`, or `irrelevant`.
- Reuse stable prompt prefixes for Meta's automatic prompt caching; record input/cached token usage, latency, model, and stage.
- Reuse versioned stored summaries as compact context and Meta's prefix cache for the stable prompt; do not cache final decisions across messages.
- Measure quality against labeled conversations before claiming an accuracy percentage.

## Non-goals

- No Discord bot implementation or Discord SDK integration.
- No assumption that a model's self-reported confidence is calibrated.
- No always-on multi-agent fan-out for every message.
- No claim of token savings or accuracy gain before usage and labeled-evaluation results exist.

## Approaches

- **Always use two models:** a lightweight model reranks candidates, then the main model classifies. Rejected because it sends each message through an extra API call, and the selected Meta-only provider currently has no confirmed cheaper reranker model than the configured Muse Spark model. Muse Wonder is priced higher on Meta's current pricing page.
- **Send all topics to the final model:** preserves maximum recall but spends input tokens on irrelevant summaries.
- **Local shortlist + strong final model (chosen):** local retrieval first; the existing Meta classifier sees a compact shortlist and makes the semantic decision. This avoids a second provider/key and cuts irrelevant context, with a future optional reranker only if a genuinely cheaper Meta model becomes available.

## Proposed flow

1. Retrieve at most 30 recent, non-closed topics in the current guild. A direct reply target is included as a strong candidate signal.
2. Build a shortlist of at most five candidates using local lexical/metadata retrieval and compact topic cards. Include a bounded fallback set when lexical scores are weak so the final model can still choose `new` or `defer`.
3. Call the existing Meta classifier with the message, shortlist, relevant reply context, stable system instructions, and a strict JSON Schema for the final decision and summary updates.
4. Validate the schema and enforce guild/topic lifecycle checks. Invalid IDs or ambiguous evidence become `defer`; local retrieval cannot write associations or topic records.
5. Record model ID, prompt/completion tokens, provider-reported cached tokens, latency, and outcome. Keep message text out of logs.

## Prompt, cache, and tool boundaries

- Keep the stable system prefix and schema before volatile message/context data so Meta can reuse a matching prompt prefix.
- Read cached-token usage from Chat Completions when present; treat absent usage details as unknown, not zero savings.
- Reuse stored versioned topic summaries as compact memory. Do not cache final classification across different messages or topic-summary versions.
- Keep retrieval tools narrow and read-only (`search_topic_candidates`, `load_topic_summary`, `resolve_reply_target`). Keep persistence and Discord actions outside model tool access.
- Model work is a bounded LangGraph workflow node, not recursive subagent spawning. The local retriever shortlists; only the main classifier proposes the final semantic decision; application validation remains authoritative.

## Evaluation

Use a representative, manually labeled dataset with interleaved conversations. Report candidate Recall@5, pairwise precision/recall/F1, false-merge rate, defer coverage, input/output tokens, cached-token share, latency, and cost. Compare current single-stage and compact-context paths on the same examples. Existing nine-row synthetic fixture is smoke/evaluation-tool input only and is not accuracy evidence.

## Constraints and references

- Keep existing APIs, durable job/outbox behavior, SQLite/Alembic, and Meta provider support backward-compatible.
- Do not add another model provider or key in this scope; do not hardcode unverified model IDs or pricing assumptions.
- Official docs describe JSON Schema structured output and automatic prompt-prefix caching for Meta Chat Completions: <https://dev.meta.ai/docs/structured-output> and <https://dev.meta.ai/docs/prompt-caching>.
- The current Meta pricing page lists Muse Spark and the higher-priced Muse Wonder; model availability/pricing can change: <https://dev.meta.ai/docs/pricing-rate-limits>.
