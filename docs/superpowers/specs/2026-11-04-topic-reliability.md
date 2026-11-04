# Topic reliability follow-up

The user authorized implementation after the backend audit and requires a clean business-oriented directory structure. Continue the Meta-only, bounded-cost backend; Discord bot setup remains external.

## Evidence and scope

Baseline: GitHub `codex/evidence-topic-classification`, commit `85aeb59`. The old chat worktree is stale and its Git parent is missing. A fresh checkout was recovered at `/home/hien/Project/coconerd`; implementation uses `codex/topic-reliability`.

The audit reproduced low-confidence assignments passing validation, synonym-only queries losing the correct candidate, overview replacement losing prior facts, and additive lists retaining superseded decisions. Source inspection also found missing job-completion lease ownership checks, no correction path for final associations, and unrecoverable outbox dependencies.

## Design and tradeoffs

Use small deterministic policies and pure memory reducers behind the existing services/repository/Unit of Work boundaries. Keep one Meta decision call per pass and the durable two-call lifetime budget. A second LLM reviewer or dense embedding service would add cost/dependencies without a representative benchmark; do not introduce either in this follow-up. Bounded lexical expansion improves known paraphrases but is not general semantic retrieval.

1. Reject low-confidence assignments conservatively, validate memory replacements against supplied topic memory and exact target quotes, and version the policy/prompt. Confidence is not a calibrated probability.
2. Separate summary reduction and topic/outbox projection from message orchestration. Preserve earlier overview facts; allow explicit evidence-backed replacement/removal of existing facts. Retain historical summary versions. Show recent memory items in compact cards.
3. Improve bounded local synonym/context retrieval and batch summary reads; retain guild scope, direct reply priority and five-card/1,600-character limits. No extra model calls.
4. Fence job state changes by lease owner and current lease, handle expired work safely, and make terminal outbox dependencies visible/recoverable without duplicate automatic side effects.
5. Provide an authenticated, auditable manual correction/review path for misassigned/deferred messages, with derived-memory and pending-action consistency. Do not silently erase actions already performed in Discord.
6. Update regression/evaluation cases, API/architecture documentation and an honest readiness report. Run the full offline suite, formatter/linter and migration checks applicable to schema changes. Do not claim Discord or current Meta accuracy from mock tests.

## Boundaries

No bot login/setup, paid tests, production migration, remote deployment or provider change. Existing `.env`/runtime data must not be read or copied; the recovered checkout contains no credentials or live database. No broad reorganization or framework upgrade. Modules are extracted for a concrete responsibility, not to meet an arbitrary line limit. Any new public API is additive and documented.

## Manual review API contract

All endpoints below require `X-Admin-API-Key` and scope every lookup to the path guild. They do not call Meta. Original message content and historical decisions/summaries remain unchanged.

- `GET /api/v1/guilds/{guild_id}/messages/{message_id}/review`: Discord message ID; returns current association revision (0 if unclassified), topic, processing state/budget, latest decision and latest correction. Use the revision for optimistic concurrency.
- `POST .../messages/{message_id}/corrections`: requires `request_id`, moderator-supplied `actor`, `reason`, `expected_revision`, nullable `target_topic_id`, and reviewed summary snapshots for exactly the old/new affected topics. Each snapshot includes `expected_version`, overview/lists and `source_message_ids` (Discord IDs). Sources must belong to the topic after the move; nonempty memory needs sources. The target must exist and not be closed. Null means manually unassigned. No automatic creation of a topic.
- Correction atomically changes association, closes the message job without resetting its model budget, appends audited decision and summary versions, rebuilds the lexical index, cancels unsent affected-topic actions and pauses Discord synchronization for affected topics. Active action leases and active message processing cause 409. Succeeded/uncertain attempted actions are retained in the review history; no automatic delete/replay on Discord.
- `GET .../topics/{topic_id}/sync`: synchronization state, current topic version and paginated action history. Existing topic message/summary endpoints supply content for reconciliation.
- `POST .../topics/{topic_id}/resume-sync`: requires `request_id`, `actor`, `reason`, `expected_version`, `discord_reconciled=true` and a verified `discord_thread_id`. The moderator confirms Discord reflects the current DB state, including messages received during the pause. A concurrent topic change causes 409. Resume records audit and unpauses future actions; it never replays historical actions.
- `POST .../actions/{action_id}/recover`: administrator resolves DEAD or expired CLAIMED actions using `resolution=not_performed|performed`, expected attempt count and the same audit fields. `not_performed` permits one further attempt without erasing the lifetime attempt counter. `performed` records verified Discord IDs instead of re-executing. Live leases, cancelled actions, paused topics and stale attempt counts cause 409. Recovery of a failed CREATE_THREAD makes its DependencyFailed children pending again; no succeeded child is replayed.

`request_id` is unique per guild across review operations. Same ID plus identical operation/resource/body returns the saved response; another body is 409. `actor` is an audit label asserted by the shared admin-key holder, not a verified Discord identity. The server validates IDs, revisions and references, not the semantic truth of moderator-provided facts or external Discord confirmations. Every failed write rolls back all changes.

Rationale: stored model summaries have no fact-level provenance, so subtracting a wrong message by replaying historical model deltas could retain unsupported facts. Requiring an explicitly reviewed full snapshot is conservative and costs no tokens; it adds moderator work. Synchronization pause prevents inconsistent pending actions while external Discord effects are reconciled by the bot/operator.

## Final review compatibility ruling

A reproduced stale-ACK case showed owner/expiry fencing is insufficient when the same bot worker_id reclaims an action. Revision 0003 also adds nullable `discord_actions.lease_token`. New claims issue a fresh token; claim responses expose it and complete/fail must echo it. Missing/old token on a tokenized lease returns 409; legacy leases without a token remain compatible until reclaimed. The HTTP field addition is additive, but requiring its echo is an intentional integration tightening. Update bot clients alongside the backend; no bot implementation is included here.
