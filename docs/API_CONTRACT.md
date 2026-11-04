# Discord bot API contract

Start with [backend/database setup](BACKEND_SETUP.md) and the [bot integration guide](BOT_INTEGRATION.md) for a runnable local smoke flow, action mapping and recovery rules.

Base path: `/api/v1`. JSON is UTF-8. Bot routes require `X-API-Key`; administrator routes require the separate `X-Admin-API-Key`. Responses include `X-Request-ID`. Requests exceeding `MAX_REQUEST_BYTES` return `413`; rate limits return `429` with `Retry-After`.

Topic summary reads share the bot request rate limit. Empty or whitespace-only configured credentials fail closed with `503`; invalid supplied keys, including non-ASCII values, return `401`.

## Configure guild access

`PUT /admin/guilds/{guild_id}/settings`

```json
{"enabled": true, "allowed_channel_ids": ["channel_001"], "retention_days": 365}
```

The backend rejects ingestion for a guild or channel absent from this allowlist. DM ingestion is unsupported.

## Ingest message

`POST /messages` returns `202` after message and durable processing-job rows commit. Duplicate `(guild_id, message_id)` deliveries return the same accepted shape without adding another message or job.

```json
{
  "guild_id": "guild_001",
  "channel_id": "channel_001",
  "message_id": "message_001",
  "author_id": "user_001",
  "author_name": "Hien",
  "content": "Meta Hackathon nên làm gì?",
  "created_at": "2026-11-04T09:00:00+07:00",
  "reply_to_message_id": null
}
```

Response: `{"message_id":"message_001","status":"accepted"}`.

Send each original message with its real timestamp and `reply_to_message_id`; do not combine unrelated messages into a long text. The response acknowledges storage, not a finished topic decision. The server gathers bounded context itself. A later clarification is another normal `POST /messages`; no separate retry or reassessment endpoint is needed.

Ambiguous messages may remain deferred. An explicit reply to the target, or a same-author clarification such as `ý mình là ...`, in the same channel within ten minutes can trigger one reassessment if budget remains. Duplicate delivery does not retrigger it. Deferred/irrelevant messages produce no Discord actions; after expiry a deferred message stays unassigned. Already assigned messages are not automatically moved to another topic. There is currently no public message-decision/job-status endpoint.

## Claim and acknowledge Discord actions

- `POST /actions/claim` request: `{"worker_id":"bot-worker-01","limit":20}`.
- `POST /actions/{action_id}/complete` request: `{"worker_id":"bot-worker-01","lease_token":"00000000-0000-4000-8000-000000000001","discord_thread_id":"thread_001","discord_message_id":null}`.
- `POST /actions/{action_id}/fail` request: `{"worker_id":"bot-worker-01","lease_token":"00000000-0000-4000-8000-000000000001","error_type":"DiscordUnavailable","error_message":"temporary failure","retryable":true}`.

Claim returns an array of actions, or `[]` when none are eligible. The action enum includes `CREATE_THREAD`, `APPEND_MESSAGE`, `UPSERT_SUMMARY`, and `RENAME_THREAD`; current projection/recovery producers do not emit `RENAME_THREAD`. Each action has a stable `action_id`; the bot should use it as its idempotency key when executing Discord operations. A `CREATE_THREAD` completion must include the resulting `discord_thread_id`. A repeated identical completion is safe. `APPEND_MESSAGE` and summary updates that depend on a new thread remain unclaimable until the create action succeeds. Pending/claimed actions for one topic are serialized, including backoff; different topics may proceed concurrently.

Example action:

```json
{
  "action_id": "action_001",
  "type": "CREATE_THREAD",
  "topic_id": "topic_001",
  "guild_id": "guild_001",
  "channel_id": "channel_001",
  "payload": {
    "title": "Meta AI Hackathon",
    "source_message_id": "message_001",
    "source_author_name": "Hien",
    "source_created_at": "2026-11-04T09:00:00+07:00",
    "source_content": "Meta Hackathon nên làm gì?"
  },
  "status": "CLAIMED",
  "lease_token": "00000000-0000-4000-8000-000000000001"
}
```

The bot posts a clearly attributed copy and source link; Discord cannot move the original message into a thread.

Claim has no top-level thread ID or lease deadline. Fetch the thread from `GET /topics/{topic_id}?guild_id=...` or the bot's persisted mapping; complete within the configured action lease (default 60 seconds). There is no lease-renewal endpoint. Preserve receipts for completed Discord operations before retrying ACKs; lease fencing does not guarantee exactly-once Discord effects.

Claim is global to this backend: it has no guild/channel filter, and `worker_id` is an ownership label, not a guild authorization scope. Consumers sharing the backend must be able to route actions for every configured guild or use a dispatcher; the shared bot key is not a per-guild credential.

## Read topics and summaries

- `GET /topics/{topic_id}?guild_id=...`
- `GET /topics/{topic_id}/messages?guild_id=...&limit=50&before=...`
- `GET /topics/{topic_id}/summary?guild_id=...`
- `GET /api/v1/health`

All topic reads require `guild_id`; cross-guild IDs return `404`. Message pagination accepts `limit` from 1–100 and an ISO-8601 `before` timestamp.

## Admin operations

- `PUT /admin/model-config?guild_id=...` stores a guild override. Without `guild_id`, it updates the global model.
- `GET /admin/model-config?guild_id=...` reads the matching effective configuration.
- `POST /admin/topics/{topic_id}/close?guild_id=...` explicitly closes a topic.
- `DELETE /admin/topics/{topic_id}?guild_id=...` deletes the topic and its associated message data.
- `DELETE /admin/guilds/{guild_id}/data` deletes guild settings and stored conversation data.

## Error examples

- `401`: missing or invalid API key.
- `403`: guild/channel is not enabled.
- `404`: topic/action is absent in the requested guild.
- `409`: action lease owner mismatch or conflicting completion.
- `413`: request body exceeds configured size.
- `422`: invalid JSON/schema, invalid timestamp, or missing thread ID on create completion.
- `429`: rate limit reached; honor `Retry-After`.
- `503`: corresponding API credential is not configured.

## Moderator review (additive)

Five administrator endpoints under `/api/v1/guilds/{guild_id}` use `X-Admin-API-Key`:

- `GET /messages/{message_id}/review`: source text, association revision, job/call budget, latest decision/correction.
- `POST /messages/{message_id}/corrections`: revision-checked assignment and full reviewed memory snapshots.
- `GET /topics/{topic_id}/sync?limit=50&offset=0`: version, pause state and action history (limit 1–100).
- `POST /topics/{topic_id}/resume-sync`: confirms external reconciliation against the latest topic version.
- `POST /actions/{action_id}/recover`: audited resolution of DEAD or expired CLAIMED work.

`message_id` here is the Discord message ID. `request_id` is required on every write and unique across review operations in a guild: identical retries return the original receipt, changed bodies return 409. `actor` is a moderator-supplied label under a shared admin key, not verified Discord user authentication. Missing/cross-guild resources return 404; stale revisions, live leases and superseded actions return 409; invalid sources/command fields return 422. All writes are transactional; no paid model call or direct Discord request occurs.

See [manual review examples and reconciliation rules](MANUAL_REVIEW.md). Existing endpoints and fields remain. Action claim responses now add `lease_token`; clients must echo it in complete/fail for newly claimed actions (missing/stale token → 409). This is a required bot integration update; existing un-tokenized leases remain compatible until their next claim.

Action lease fencing uses status, owner, expiry and per-claim token; reusing worker_id cannot authorize an ACK from an older claim.

## Discord channel configuration and topics

- `GET /api/v1/guilds/{guild_id}/settings` uses the bot key and returns saved settings.
- Admin settings writes accept nullable `output_channel_id`; it must be separate from
  `allowed_channel_ids`. Writes continue to require the admin key.
- `GET /api/v1/topics?guild_id=...&channel_id=...&include_closed=false&limit=50`
  lists topics by origin channel, including message counts. The limit is 1–100.
- Summary reads accept optional `channel_id`; a different origin channel returns 404.
  This does not replace Discord ACL checks for messages grouped across channels.
- Completing a leased `CREATE_THREAD` action persists the mapping atomically. A topic
  already mapped to a different thread returns 409 without completing the action.
  No separate, unfenced thread-mapping endpoint is exposed.

Run `alembic upgrade head` when upgrading an existing database. The channel migration
preserves messages and topics and derives legacy origins from the earliest association.
