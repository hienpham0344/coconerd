# Testing

The suite uses pytest, pytest-asyncio, HTTPX ASGI testing, and an isolated SQLite database. No Meta key or network call is required.

```bash
pytest
ruff check backend tests
ruff format --check backend tests
```

Coverage includes topic lifecycle rules, guild model override selection, authenticated and allowlisted ingestion, duplicate delivery, durable job creation, guild isolation, outbox dependency ordering, action completion retry, an offline provider-to-topic/summary/action flow, and metric calculation. `tests/fixtures/evaluation/interleaved_conversations.jsonl` is a small synthetic fixture for exercising evaluation tooling; it is not a benchmark result. To calculate pairwise precision/recall/F1 from actual predictions, run `python scripts/evaluate_grouping.py tests/fixtures/evaluation/interleaved_conversations.jsonl path/to/predictions.jsonl`, where each prediction row has `message_id` and `predicted_topic_id` (or `null` for deferred messages).

For manual API smoke checks, run Alembic migrations, start the API and worker in separate terminals, configure a guild/channel with the admin key, then POST a message with the bot key. Swagger/OpenAPI is served at `/docs` and `/openapi.json`.

The suite does not claim that live Meta API behavior has been exercised. It also does not synthesize evaluation metrics; a separate labeled conversation dataset is needed to measure topic grouping quality.
