# Agent workflow

```text
Discord message
  -> persist message + processing job transactionally
  -> worker claims a job lease
  -> retrieve recent ACTIVE / DORMANT / RESUMED topics for that guild
  -> model returns new / existing / defer / irrelevant
  -> validate guild ownership and topic lifecycle
  -> persist association + decision + memory version + outbox actions atomically
  -> bot claims eligible actions and acknowledges Discord results
```

The Meta prompt treats message content as untrusted data and explicitly disallows using it as system instructions. It asks the provider to defer ambiguous links and to distinguish proposals, decisions, open questions, and action items. A model response must validate against `TopicDecision`; malformed output fails the job and follows bounded retry rather than being treated as success.

After the configured inactivity interval, the worker changes `ACTIVE` to `DORMANT` and ends the open episode. A later supported association can resume the topic and open another episode; inactivity never marks a topic `CLOSED`.

`MockMetaProvider` is deterministic and development/test only. It creates a topic when there are no candidates and defers semantic matching when candidates exist. It is deliberately not presented as an evaluation of Meta quality.

Summaries are incremental: each changed version combines the previous structured memory with the latest model-proposed updates, and includes source message IDs. A version and `UPSERT_SUMMARY` action are written only when the overview or structured items change. The history is retained by version. The model never accesses Discord APIs.
