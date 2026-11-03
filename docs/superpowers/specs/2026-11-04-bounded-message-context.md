# Bounded message context for topic classification

## Decision

The Discord bot sends each original message with its ID, guild, channel, author,
timestamp, and optional reply ID to the existing `POST /api/v1/messages` endpoint.
The API persists and acknowledges each message before classification. The worker
classifies each message separately, using a bounded selection of earlier stored
messages as context. Context is evidence, not a declaration that all messages
belong to one topic.

## Server behavior

- Read only prior messages from the same guild and channel. Never include the
  current message, later messages, or messages from another channel.
- Follow at most three reply ancestors, including old replies outside the recent
  window. Reject missing, future, or cross-channel ancestors.
- Add recent messages from the previous ten minutes, newest first for selection.
  Keep at most six context messages total, 400 characters per message and 1,600
  content characters overall. Prioritize reply ancestors over recent messages.
- Send context to the model as individual JSON objects with message ID, author,
  timestamp, relationship, and truncated content. Sort selected objects in
  chronological order for reading. The prompt explicitly warns that nearby
  messages may be unrelated and forbids transferring their facts to the target.
- Record selected context message IDs with the AI decision for audit. Preserve
  the existing structured decision schema and topic/summary/outbox transaction.
- No additional model call or external provider is required. A missing or empty
  context is valid and uses the original single-message behavior.

## Boundaries

No bot implementation, HTTP batch endpoint, debounce, delayed job, schema
migration, or topic accuracy claim is part of this increment. These can be added
later without changing the per-message storage contract. Existing rate limits
still apply to each HTTP request.

## Verification

Exercise the selector with interleaved topics, old replies, out-of-order ingest,
blank messages, cross-channel/guild references, and the character budget. Verify
the Meta request contains distinct context objects and that the decision audit
stores their IDs. Run focused and full tests plus Ruff.
