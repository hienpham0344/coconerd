# Evidence-based topic classification

Implement the user's approved recommendations on the existing Meta-only backend.
Preserve the one-message API, original messages, prior changes, and transactional
association/summary/outbox writes. No bot setup, dependency upgrade, or vector DB.

- Versioned policy distinguishes uncertain references from irrelevant text.
  Require target-message evidence for assignments, validate evidence IDs and the
  actual shortlist, and defer multi-topic input. Confidence is not calibrated
  probability. Matching titles alone must not force a merge.
- Deterministic read-only tools gather bounded reply context, search all eligible
  same-guild topics through a SQLite token index, and read scoped evidence.
  Accent normalization and a small explicit alias map improve lexical recall;
  original text is preserved. At most five compact cards enter Meta.
- Add durable job fields for at most one reassessment and two model calls total,
  including failed calls/retries. A deferred unassigned message waits ten minutes
  for an explicit reply or same-author clarification in the same channel.
  An implicit clarification must not skip a newer same-author message or
  resolve equal-timestamp ambiguity; explicit replies remain authoritative links.
  Process already-arrived clarification too. Expiry performs no paid work.
- Reassessment only updates a DEFERRED association, retaining prior decisions.
  Assigned messages are not automatically reassigned; this prevents stale
  summaries/outbox actions from automatic correction. Deferred and invalid
  decisions produce no topic memory or Discord actions.
- Local rules use zero model calls. Lazily create Meta after a durable budget
  reservation. Tools are orchestrated by code; an additional model subagent or
  semantic RAG remains conditional on measured gains.
- Add reproducible synthetic development/holdout fixtures and an opt-in live
  runner with a hard call bound. Metrics include shortlist recall for existing
  topics, outcome accuracy, wrong merges, duplicate-new decisions, defer precision,
  assignment coverage, and known token/latency data. Reject missing/duplicate
  predictions. Synthetic results do not establish real Discord accuracy.

Migration is additive and backfills the topic index. Verify on a disposable DB;
do not apply it to the user's active data automatically. No commit/push requested
for this increment. The six recommendations and implementation were approved in
chat; no additional design approval is needed.

Follow-up authorization (2026-11-04): the user explicitly requested deploying
the database changes. The configured SQLite file did not yet exist, so both
migrations were applied to initialize it; there was no prior database to back
up. Verification and the deployment boundary are recorded in `docs/TESTING.md`.
