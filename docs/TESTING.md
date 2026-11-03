# Testing

The suite uses pytest, pytest-asyncio, HTTPX ASGI testing, and an isolated SQLite database. No Meta key or network call is required.

```bash
pytest
ruff check backend tests
ruff format --check backend tests
```

Coverage includes topic lifecycle rules, guild model override selection, authenticated and allowlisted ingestion, duplicate delivery, durable job creation, guild isolation, outbox dependency ordering, action completion retry, local shortlist ranking, strict provider schema/usage parsing, an offline provider-to-topic/summary/action flow, and evaluation metrics. `tests/fixtures/evaluation/interleaved_conversations.jsonl` is a small synthetic fixture for exercising evaluation tooling; it is not a benchmark result.

Prediction JSONL rows use `message_id`, `predicted_topic_id` (or `null` for deferred messages), and `candidate_topic_ids` (the shortlist persisted in each AI decision payload). Run `python scripts/evaluate_grouping.py tests/fixtures/evaluation/interleaved_conversations.jsonl path/to/predictions.jsonl` to calculate pairwise precision/recall/F1 and candidate Recall@5. The latter checks whether the labeled topic appeared among the first five candidates; it does not measure the final model decision. A representative labeled dataset is required for accuracy claims.

For manual API smoke checks, run Alembic migrations, start the API and worker in separate terminals, configure a guild/channel with the admin key, then POST a message with the bot key. Swagger/OpenAPI is served at `/docs` and `/openapi.json`.

The suite does not claim that live Meta API behavior has been exercised. It also does not synthesize evaluation metrics; a separate labeled conversation dataset is needed to measure topic grouping quality.

## Ranh giới kiểm thử

- Use-case tests dùng fake/spy Unit of Work để kiểm tra policy, guild scope, candidate IDs, commit và rollback khi hoàn tất job thất bại.
- Repository tests kiểm tra SQL, thứ tự xóa, bộ lọc, DTO mapping và việc repository không tự commit. Chúng bổ sung cho integration test với SQLite thật.
- API contract tests kiểm tra route, schema, auth, response/error mapping và đường request qua middleware. OpenAPI giữ nguyên hợp đồng trước refactor.
- Worker tests kiểm tra retry/dead-letter, heartbeat, cấu hình provider, retention và topic dormancy.

**Kết quả kiểm chứng ngày 2026-11-03:** toàn bộ suite qua, **85 passed in 7.01s**, gồm API/SQLite async, LangGraph processing, OpenAPI contract và ranh giới kiến trúc. Ruff lint/format và `git diff --check` cũng qua.

Một số lần chạy trước trong môi trường thực thi bị giới hạn đã treo ở async SQLite/LangGraph. Chạy cùng suite ngoài giới hạn đó đã thành công; nguyên nhân chi tiết chưa xác minh, không thay thư viện hoặc production code để né lỗi môi trường. Unit/SQL-spy tests vẫn không thay thế integration test; suite hiện tại cũng không chứng minh lease safety dưới tải đồng thời hay chất lượng model thật.
