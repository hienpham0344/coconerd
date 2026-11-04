# Token-aware topic agent

## Goal

Keep the current Meta-only classifier useful for Discord topic assignment while
reducing unnecessary model work and making token cost measurable. The Discord bot
remains outside this repository.

## Current evidence

- The backend already reads a bounded reply/recent-message context and ranks up
  to five topic cards locally before one Meta call per message.
- In an earlier live synthetic trial, a 2,048-token output cap was exhausted by
  reasoning and the provider returned no decision. A 4,096-token trial returned
  a valid reply classification. These are integration observations, not accuracy
  or cost benchmarks.
- The key was absent at design time. After the user supplied it locally, three
  synthetic calls completed at low effort with the 2,048-token cap; see
  `docs/TESTING.md` for measured results and semantic limitations.

## Options considered

1. **Model subagents and tool loops for every message.** They may help some hard
   cases but add tool schemas, extra model turns, latency, and billed reasoning.
2. **One Meta call with local read-only retrieval (chosen now).** Reuse the
   existing context selector and topic ranker; set a low reasoning effort,
   short-circuit empty text, and measure provider-reported reasoning tokens.
3. **Embedding/vector RAG for every message.** It can retrieve semantically
   related old topics, but adds indexing, migrations, storage, and evaluation
   needs before we know whether the current shortlist misses them.

## First increment

- Add `COCONERD_LLM_REASONING_EFFORT` (`minimal`, `low`, `medium`, `high`,
  `xhigh`, `max`) with `low` as the default for Muse Spark. Continue to allow
  `COCONERD_LLM_MAX_TOKENS`; do not silently raise the cap until live low-effort
  output is measured. The existing `LLM_MAX_TOKENS` alias remains accepted.
- Pass `reasoning_effort` on the existing Chat Completions request. Persist
  provider-reported reasoning tokens with prompt/completion/cache tokens and
  latency; absent usage stays unknown.
- Distinguish `finish_reason=length` from malformed model JSON. This makes
  budget exhaustion visible without logging raw message content or credentials.
- Classify blank text locally as `irrelevant` with zero model calls and known
  zero token usage. The API still persists the original message and its job.
- Preserve existing JSON Schema, topic association, summary, outbox, guild
  isolation, bounded retries for temporary failures, and one-message API contract.
- Review adjustment: truncation stops retries with job status `DEAD`, retaining
  the original message. Repeating the same exhausted budget can waste paid
  tokens. Operators must review configuration before retrying; there is no
  public retry endpoint and no automatic token-budget increase.

## Agent tools, skills, subagents, and RAG gate

The existing reply lookup, recent-message selector, candidate retrieval, and
summary reads are bounded read-only tools executed by application code before
the model. We keep their behavior explicit rather than advertising function
schemas to Meta on every message. A dynamic topic-search tool or second model
pass may be introduced only for measured candidate-recall failures, with one
read-only lookup and a strict per-message call/token budget. A smaller model
subagent is deferred until a Meta-only option is verified to improve cost and
quality on labeled data. Vector RAG is deferred until retrieval Recall@5 on
representative conversations shows a semantic/old-topic gap that local search
cannot resolve.

## Verification

- Tests prove the provider sends low reasoning effort, records optional
  reasoning usage, reports truncation, and never calls Meta for blank text.
- Run the full offline suite and Ruff. Once a key is present, compare the same
  synthetic cases at low effort against the earlier observations, recording
  outcomes, reasoning/output tokens, cache tokens, and latency. No accuracy or
  savings claim follows from a few examples.

Meta documents that reasoning tokens are billed output tokens and count toward
the output cap: <https://dev.meta.ai/docs/reasoning>. Its tool-calling API
requires application-managed execution and an additional model turn when a tool
is used: <https://dev.meta.ai/docs/tool-calling>.
