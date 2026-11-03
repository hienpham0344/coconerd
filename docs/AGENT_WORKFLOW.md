# Agent workflow

HTTP ingestion gọi `application/services/messages.py` để lưu message/job qua Unit of Work. Worker dùng cùng service cho xử lý; `agent_workflow.py` điều phối retrieval và provider, còn persistence nằm trong `infrastructure/database/repositories/`. [Kiến trúc backend](BACKEND_ARCHITECTURE.md) mô tả ranh giới module và transaction.

```text
Discord message
  -> persist message + processing job transactionally
  -> worker claims a job lease
  -> select earlier same-channel messages (reply ancestry first, then recent)
  -> retrieve up to 30 recent ACTIVE / DORMANT / RESUMED topics for that guild
  -> local lexical ranking selects up to five compact topic cards (direct reply first)
  -> Meta returns a strict JSON-Schema decision: new / existing / defer / irrelevant
  -> validate guild ownership and topic lifecycle
  -> persist association + decision + memory version + outbox actions atomically
  -> bot claims eligible actions and acknowledges Discord results
```

The Meta prompt treats message content as untrusted data and explicitly disallows using it as system instructions. It asks the provider to defer ambiguous links and to distinguish proposals, decisions, open questions, and action items. A model response must validate against `TopicDecision`; malformed output fails the job and follows bounded retry rather than being treated as success.

The server classifies each original message separately. It may add up to three reply ancestors and nearby messages from the preceding ten minutes, limited to six messages and 1,600 content characters total (400 per message). Context stays as separate records with IDs, author, time and relationship; it is evidence, not proof that adjacent messages share a topic. Only earlier messages in the same guild and channel are eligible. Selected IDs are stored with the AI decision. There is no debounce, HTTP batch endpoint or extra model call in this workflow.

The local ranker scores title matches above description and summary matches. It is only a bounded shortlist: lexical overlap does not prove that messages belong to the same discussion. A direct-reply topic remains first, and the application still checks guild ownership and lifecycle before persisting an association. Topic cards cap title, description, overview, and list sizes before they enter the prompt.

The stable system instructions and schema precede variable message/topic context. The provider uses a shared versioned cache key and records provider-reported prompt, completion, and cached tokens plus latency. Missing cache usage remains unknown. No topic decision is reused across messages.

After the configured inactivity interval, the worker changes `ACTIVE` to `DORMANT` and ends the open episode. A later supported association can resume the topic and open another episode; inactivity never marks a topic `CLOSED`.

`MockMetaProvider` is deterministic and development/test only. It creates a topic when there are no candidates and defers semantic matching when candidates exist. It is deliberately not presented as an evaluation of Meta quality.

Summaries are incremental: each changed version combines the previous structured memory with the latest model-proposed updates, and includes source message IDs. A version and `UPSERT_SUMMARY` action are written only when the overview or structured items change. The history is retained by version. The model never accesses Discord APIs.
