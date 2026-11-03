# Discord bot API contract

Base path: `/api/v1`. JSON is UTF-8. Bot routes require `X-API-Key`; administrator routes require the separate `X-Admin-API-Key`. Responses include `X-Request-ID`. Requests exceeding `MAX_REQUEST_BYTES` return `413`; rate limits return `429` with `Retry-After`.

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

## Claim and acknowledge Discord actions

- `POST /actions/claim` request: `{"worker_id":"bot-worker-01","limit":20}`.
- `POST /actions/{action_id}/complete` request: `{"worker_id":"bot-worker-01","discord_thread_id":"thread_001","discord_message_id":null}`.
- `POST /actions/{action_id}/fail` request: `{"worker_id":"bot-worker-01","error_type":"DiscordUnavailable","error_message":"temporary failure","retryable":true}`.

Actions use `CREATE_THREAD`, `APPEND_MESSAGE`, `UPSERT_SUMMARY`, or `RENAME_THREAD`. Each action has a stable `action_id`; the bot should use it as its idempotency key when executing Discord operations. A `CREATE_THREAD` completion must include the resulting `discord_thread_id`. A repeated identical completion is safe. `APPEND_MESSAGE` and summary updates that depend on a new thread remain unclaimable until the create action succeeds.

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
  "status": "CLAIMED"
}
```

The bot posts a clearly attributed copy and source link; Discord cannot move the original message into a thread.

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
