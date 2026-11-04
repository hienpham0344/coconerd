# Testing

## Tiếp tục kiểm thử bot readiness — 2026-11-04

- Chạy lại toàn bộ suite sau gián đoạn: `COCONERD_MODEL_API_KEY= .venv/bin/pytest -q --tb=short` → **250 passed, 71 warnings in 62.43s**. Warnings là Alembic `path_separator` và SQLAlchemy `Session.flush(objects=...)` deprecations.
- Hai test còn đỏ đã được tái hiện trước khi sửa: key sai chứa Unicode gây `TypeError` thay vì 401; đọc summary bỏ qua rate limit (404 thay vì 429 khi quota đã hết). Đã so sánh credential dưới dạng UTF-8 bytes và dùng chung bot auth/rate-limit dependencies cho summary.
- Các hồi quy từ task trước cũng qua: credential cấu hình rỗng bị chặn; action cùng topic được tuần tự hóa, topic khác vẫn xử lý được; API → DB migrate tạm → worker → bot giả lập, duplicate delivery đồng thời, memory replacement, retry/backoff, ACK lặp/lease token và giới hạn provider timeout/output truncation.
- Ruff check, Ruff format check trên `backend tests scripts alembic` và `git diff --check` đều qua. Lần chạy trong sandbox không tiến triển; chạy ngoài sandbox hoàn tất. Nguyên nhân sâu của khác biệt môi trường chưa xác minh.
- Smoke tiếng Việt tổng hợp: **4/4** khớp outcome/topic mong đợi, **3 Meta calls + 1 local**, không error/skipped. Bao gồm Telex đăng nhập web, `dr do` thiếu ngữ cảnh, code literal và phủ định trong reply. Usage quan sát: **4.646 input + 3.347 output = 7.993 tokens**; cached/reasoning đã nằm trong tổng tương ứng. Đây là smoke nhỏ có nhãn tác giả, không phải accuracy Discord thực tế.
- Artifacts: [cases](evaluations/2026-11-04-resumed-language-cases.jsonl), [predictions](evaluations/2026-11-04-resumed-language-predictions.jsonl), [report và cấu hình/hash](evaluations/2026-11-04-resumed-language.json). Tối đa 4 call được cho phép; thực tế dùng 3, không retry.
- Không migrate DB runtime, đăng nhập Discord hoặc khởi động dịch vụ nền. Còn cần thử bot thật với permission/thread, rate limit Discord, mất ACK sau side effect và chống lặp bằng `action_id`; kiểm thử tải/soak và dữ liệu Discord gán nhãn vẫn chưa thực hiện.

The suite uses pytest, pytest-asyncio, HTTPX ASGI testing, and an isolated SQLite database. No Meta key or network call is required.

```bash
pytest
ruff check backend tests scripts alembic
ruff format --check backend tests scripts alembic
```

Coverage includes topic lifecycle rules, guild model override selection, authenticated and allowlisted ingestion, duplicate delivery, durable job creation, guild isolation, outbox dependency ordering, action completion retry, local shortlist ranking, strict provider schema/usage parsing, an offline provider-to-topic/summary/action flow, and evaluation metrics. `tests/fixtures/evaluation/interleaved_conversations.jsonl` is a small synthetic fixture for exercising evaluation tooling; it is not a benchmark result.

The legacy `scripts/evaluate_grouping.py` reads `message_id`, `predicted_topic_id`, and `candidate_topic_ids` for pairwise metrics. It compares intersecting IDs and can hide missing predictions; use the strict agent evaluator below for the current workflow. Candidate Recall@5 measures shortlist inclusion, not the final decision.

For manual API smoke checks, run Alembic migrations, start the API and worker in separate terminals, configure a guild/channel with the admin key, then POST a message with the bot key. Swagger/OpenAPI is served at `/docs` and `/openapi.json`.

The suite does not claim that live Meta API behavior has been exercised. It also does not synthesize evaluation metrics; a separate labeled conversation dataset is needed to measure topic grouping quality.

## Ranh giới kiểm thử

- Use-case tests dùng fake/spy Unit of Work để kiểm tra policy, guild scope, candidate IDs, commit và rollback khi hoàn tất job thất bại.
- Repository tests kiểm tra SQL, thứ tự xóa, bộ lọc, DTO mapping và việc repository không tự commit. Chúng bổ sung cho integration test với SQLite thật.
- API contract tests kiểm tra route, schema, auth, response/error mapping và đường request qua middleware. OpenAPI giữ nguyên hợp đồng trước refactor.
- Worker tests kiểm tra retry/dead-letter, heartbeat, cấu hình provider, retention và topic dormancy.

Lần kiểm chứng trước đợt evidence-agent: **99 passed in 11.91s**. Kết quả này là mốc lịch sử; không phải số test cuối của thay đổi mới.

**Kiểm chứng cuối evidence-agent ngày 2026-11-04:** `.venv/bin/pytest -q --tb=short` → **177 passed, 2 warnings in 58.82s**. Hai cảnh báo là Alembic deprecation về `path_separator`. Ruff check/format trên `backend tests scripts alembic`, `git diff --check` và kiểm tra liên kết tài liệu đều qua. Có hồi quy cho giới hạn hai reservation đồng thời, chỉ xét lại một lần, lời giải thích đến sớm/sai đích, topic đóng trước thao tác ghi, xóa chỉ mục, metric thiếu prediction/usage và CLI từ chối ghi đè.

Một số lần chạy trước trong môi trường thực thi bị giới hạn đã treo ở async SQLite/LangGraph. Chạy cùng suite ngoài giới hạn đó đã thành công; nguyên nhân chi tiết chưa xác minh, không thay thư viện hoặc production code để né lỗi môi trường. Unit/SQL-spy tests vẫn không thay thế integration test; suite hiện tại cũng không chứng minh lease safety dưới tải đồng thời hay chất lượng model thật.

## Meta live smoke trước policy v3 — 2026-11-04

Ba câu tổng hợp được gọi trực tiếp qua provider thật `muse-spark-1.3`, `reasoning_effort=low`, `max_tokens=2048`, không retry. Không gửi dữ liệu Discord thật hoặc ghi vào database ứng dụng.

| Ca | Outcome quan sát | Input tokens | Output tokens | Reasoning tokens | Cached input tokens | Thời gian |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Mở thảo luận kế hoạch beta | `new` | 555 | 825 | 654 | 0 | 9,03 s |
| Reply chốt thứ Năm, có câu gốc và topic beta | `existing`, đúng `topic-beta` | 676 | 1.036 | 932 | 369 | 10,09 s |
| `ok`, hai topic ứng viên, không có câu gốc | `irrelevant` | 627 | 1.333 | 1.217 | 369 | 13,77 s |

Reasoning nằm trong output tokens; cached input nằm trong input tokens, không cộng lại. Cả ba ca trả JSON hợp lệ và không bị cắt đầu ra. Ca `ok` vẫn cần đánh giá: nếu quy tắc nghiệp vụ yêu cầu giữ câu xác nhận thiếu ngữ cảnh để xử lý sau thì `defer` phù hợp hơn `irrelevant`. Đây là smoke test kết nối/schema và vài hành vi, không phải benchmark accuracy hay phép so sánh tiết kiệm token có kiểm soát. Discord bot chưa được kiểm thử.

## Strict agent evaluation

`agent_dev.jsonl` và `agent_holdout.jsonl` trong `tests/fixtures/evaluation/` có 10 snapshot tổng hợp mỗi split, conversation/message IDs tách biệt. Bao gồm thiếu ngữ cảnh, interleaving, topic tương tự, alias, topic cũ, đổi chủ đề trong reply, nhiều chủ đề và lời giải thích. Nhãn do người triển khai đặt, còn tạm thời; một số ca dùng cùng mẫu giữa hai split. Chúng không tạo thành holdout độc lập đại diện Discord thực tế.

Runner sử dụng local ranker, giới hạn context và workflow/validator thật trên snapshot; không ghi DB hoặc tạo outbox. Kiểm tra index DB, wakeup/retry và migration nằm trong integration tests riêng. Snapshot clarification không kiểm thử bộ lập lịch. Chỉ Meta-only; không thêm model subagent. Chạy từ repository sau khi cài môi trường:

```bash
# Offline: kiểm tra công cụ, không đánh giá độ chính xác model
python -m scripts.evaluate_agent tests/fixtures/evaluation/agent_dev.jsonl \
  --output /tmp/coconerd-dev-mock.jsonl

# Có tính phí: phải chọn live và giới hạn số lượt; không retry
python -m scripts.evaluate_agent tests/fixtures/evaluation/agent_dev.jsonl \
  --live --max-calls 3 --output /tmp/coconerd-dev-live.jsonl

# Chấm lại kết quả đã lưu; không gọi API
python -m scripts.evaluate_agent tests/fixtures/evaluation/agent_dev.jsonl \
  --predictions /tmp/coconerd-dev-live.jsonl
```

Output phải là file mới; runner từ chối ghi đè trước khi gọi model. `--max-calls` nhận 0–100, tính cả lần lỗi; hết hạn mức tạo row `skipped`, nhưng local rules vẫn chạy. Mỗi row được ghi ngay sau ca thử, có `status`, `mode`, result hoặc tên loại lỗi; không lưu nội dung exception có thể chứa dữ liệu nhạy cảm. Chấm file thiếu/thừa/trùng message IDs sẽ báo lỗi; không âm thầm bỏ ca thiếu. Không trộn kết quả mock và live.

- `outcome_accuracy`: đúng loại outcome / toàn bộ ca; `decision_accuracy` còn kiểm tra đúng topic ID cho existing. Ca lỗi/skipped vẫn nằm trong mẫu số.
- `candidate_recall_at_5`: gold existing topic có trong shortlist / toàn bộ nhãn existing. Retrieval vẫn được đo ở ca skipped nếu shortlist đã tính; không đồng nghĩa model đã phân loại ca đó.
- `wrong_merges`: dự đoán existing sai topic hoặc gold không phải existing; `wrong_merge_rate` chia cho số dự đoán existing.
- `duplicate_new`: dự đoán new khi gold là existing; không phát hiện mọi trường hợp trùng title/nghĩa ngoài nhãn.
- `defer_precision`: defer đúng / tổng dự đoán defer. `assignment_coverage`: số quyết định new/existing / toàn bộ ca. `assignment_precision`: assignment đúng loại/ID / số assignment; chưa chấm chất lượng title/summary.
- Usage có tổng phần đã biết, số ca có số đo và total chỉ khi đủ dữ liệu; unknown giữ `null`. Cached thuộc input, reasoning thuộc output. Tổng tokens chỉ là input + output.
- Latency tách `all_cases_mean` và `model_attempts_mean`; số đo theo toàn ca không được dùng làm latency model khi có local/skipped. Mẫu số trống trả `null`.

## Meta policy v3: kiểm tra có giới hạn — 2026-11-04

Chạy dev với `--live --max-calls 3`, model `muse-spark-1.3`, effort `low`, output limit 2048. Cả ba lượt trả schema/evidence hợp lệ và khớp nhãn tổng hợp:

Kết quả lưu dưới đây thuộc prompt/cache `language-v1` ở thời điểm chạy. Source hiện dùng `language-v2` và thêm guard cho câu tham chiếu ngắn; không coi kết quả cũ là kiểm chứng live của mọi thay đổi sau đó. Fixture `language_smoke.jsonl` cung cấp thêm ca tổng hợp về Telex, viết tắt, phủ định và code literals để chạy riêng bằng cùng CLI; bản thân fixture không phải báo cáo kết quả.

| Ca | Kết quả | Input | Output | Reasoning | Cached input | Provider latency |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Dashboard mới cho Atlas | `new` | 946 | 923 | 634 | 0 | 11.044 ms |
| Login mobile, cạnh tranh với web | `existing: dev-login` | 1.013 | 1.153 | 1.014 | 753 | 12.224 ms |
| `DB`, topic cơ sở dữ liệu cũ | `existing: dev-db` | 1.017 | 1.416 | 1.137 | 753 | 15.882 ms |

Hai ca `ok`/blank chạy local với zero tokens. Năm ca cần model còn lại được `skipped`; coverage toàn fixture là 5/10, không phải đã đo đủ 10 ca. Ba lượt trả phí báo tổng **2.976 input + 3.492 output = 6.468 tokens**; cached 1.506 và reasoning 2.785 là các phần nằm trong các tổng đó. Chưa có so sánh đối chứng về tiết kiệm token.

[Báo cáo dev live](evaluations/2026-11-04-dev-live.json) và [báo cáo holdout mock](evaluations/2026-11-04-holdout-mock.json) ghi rõ mode, model, policy và hash fixture. Holdout chỉ chạy mock để kiểm tra pipeline; các điểm của mock không có giá trị đo accuracy Meta. Có thể chấm lại từ [predictions dev](evaluations/2026-11-04-dev-live-predictions.jsonl) và [predictions holdout](evaluations/2026-11-04-holdout-mock-predictions.jsonl); toàn bộ dữ liệu là tổng hợp, không lấy từ Discord thật.

Chưa thử bot Discord, tải nhiều worker hoặc gán nhãn hội thoại thực tế. Còn hạn chế về paraphrase không trùng từ, slang ngoài từ điển, chọn sai evidence hợp lệ và summary hiểu sai; kiểm tra ID không giải quyết hoàn toàn các vấn đề đó.

## Khởi tạo DB cấu hình thật — 2026-11-04

Sau khi người dùng yêu cầu triển khai DB, kiểm tra xác nhận `/home/hien/Project/coconerd/data/coconerd.db` chưa tồn tại và không có API/worker coconerd đang chạy. Đã chạy `.venv/bin/alembic upgrade head` từ `/home/hien/Project/coconerd`, tạo DB mới qua revision `20261103_0001` rồi `20261104_0002`. Không có DB cũ cần sao lưu.

- DB có 14 bảng, bốn cột job mới và chỉ mục `ix_topic_terms_guild_term`; `PRAGMA integrity_check` trả `ok`, `foreign_key_check` không có vi phạm.
- `.venv/bin/alembic check` báo `No new upgrade operations detected`: schema đã khớp ORM hiện tại.
- Kiểm tra tích hợp trên bản sao tạm của chính DB vừa tạo: bật guild/channel thử, POST cùng message hai lần đều trả 202, vẫn chỉ có một message/job; worker mock hoàn tất với `SUCCEEDED`, một topic/association/summary và hai outbox actions; đọc summary qua API trả 200.
- Bản sao thử bật foreign keys; không gọi Meta. DB cấu hình thật giữ nguyên không có tin/topic/job/action tổng hợp. Không khởi động API/worker nền hoặc thiết lập bot Discord trong bước triển khai DB này.

## Reliability v4 — 04/11/2026

Fresh offline verification in the recovered checkout on `codex/topic-reliability`:

- `.venv/bin/pytest -q --tb=short`: **231 passed, 65 warnings in 60.61s**. Tests include policy/reducer/projection, HTTP review/correction, source/guild/revision guards, idempotency, paused sync, audited recovery, real SQLite rollback, lease theft and stale ACK after reclaim with the same bot worker ID.
- Migration tests upgrade a legacy disposable database to `20261104_0003`, validate alias backfill and review fields, downgrade/re-upgrade, preserve old topic data and check SQLite integrity. No runtime database was migrated.
- OpenAPI snapshot covers five new review endpoints and the `lease_token` addition to action claim/ACK/fail. Existing fields and routes remain; bot clients must echo the claim token for newly issued leases.
- Ruff lint/format, architecture tests, `git diff --check` and local documentation links checked. No new runtime dependency or lockfile change.

Warnings: 6 Alembic `path_separator` deprecations and 59 SQLAlchemy `Session.flush(objects=...)` deprecations from existing code. These are not failing tests. A test process ended with code 143 during the run; it was not counted as verification. The subsequent complete 231-test run above finished with exit code 0.

The full run initially exposed three outdated query-test expectations after adding review audit deletion and terminal cleanup; they were updated while retaining guild/order/filter assertions. The final review also reproduced an actual same-worker stale-ACK bug (200 instead of 409), then added per-claim lease tokens and verified the regression.

This was an author self-review; no independent reviewer/subagent was available. Offline correctness does not establish Meta v4 accuracy, production throughput, Discord permissions or exactly-once side effects. No paid model call, bot login or long-lived deployment was performed during that offline reliability run. Existing live v3 reports remain historical; they were not overwritten or relabeled as v4 results. See the subsequent authorized live checks below, [readiness assessment](BACKEND_READINESS.md) and [manual review integration](MANUAL_REVIEW.md).

## Meta v4 live: phân loại và sửa memory — 04/11/2026

Kiểm tra sau đợt reliability, được người dùng cho phép. Dùng Meta-only, model yêu cầu `muse-spark-1.3`, prompt/cache `coconerd-topic-classification-v4-memory-v1`, không SDK retry, không dùng chat Discord thật. Dữ liệu là snapshot tổng hợp có nhãn do người triển khai đặt, không phải benchmark độc lập.

**Lượt chính — effort `low`, tối đa 2.048 output tokens mỗi call:** 9 ca, 7 lượt gọi Meta và 2 ca xử lý local. Có 8 ca hoàn tất, khớp cả outcome/topic ID mong đợi; ca sửa memory thất bại với `MetaOutputTruncatedError`. Không có gán nhầm topic trong các kết quả đã hoàn tất.

| Ca | Quan sát |
| --- | --- |
| Mở dashboard mới | `new` |
| Login mobile, có topic web cạnh tranh | `existing`, đúng `dev-login` |
| Viết tắt DB | `existing`, đúng `dev-db` |
| `ok` không có tham chiếu | `defer`, local, zero tokens |
| Reply nhưng chuyển sang tuyển người thiết kế logo | `new` |
| Một tin nói lịch beta và lỗi login | `defer` |
| `đồng ý` có clarification | `existing`, đúng `dev-beta` |
| Tin trống | `irrelevant`, local, zero tokens |
| Dời lịch và thêm người phụ trách | Output bị cắt; chưa có decision hợp lệ |

**Một lượt chẩn đoán riêng — effort `minimal`, vẫn 2.048 output tokens:** cùng ca memory trả JSON hợp lệ, đúng `v4-atlas`. Model đề xuất replacements có quote đúng cho overview và decisions. Reducer giữ Lan phụ trách QA, bỏ lịch thứ Năm, thêm lịch thứ Sáu và Thanh phụ trách API; 7 kiểm tra trạng thái memory đều đạt, snapshot cũ không bị mutate. Overview vẫn lặp ý lịch mới bằng hai cách diễn đạt: chỉ chống trùng chuỗi chính xác, chưa chống trùng theo nghĩa. Một ca thành công chưa đủ để đổi effort mặc định hoặc kết luận `minimal` tốt hơn trên mọi ca; mặc định vẫn là `low`.

Tổng cộng có 8 lượt gọi nhận được phản hồi: 7 kết quả hợp lệ và 1 bị cắt. Trước đó, một lần chạy trong môi trường hạn chế bị dừng khi chưa ghi được prediction; không xác minh được request đã gửi hay usage của lần đó. Các lượt có kết quả chạy được ngoài môi trường hạn chế, nhưng nguyên nhân chi tiết của lần treo chưa được xác minh.

Usage đã lưu ở lượt chính: 7.762 input + 6.679 output = 14.441 tokens. Lượt chẩn đoán: 1.308 input + 1.462 output = 2.770 tokens. **17.211 là số tokens quan sát được từ kết quả hợp lệ, không phải tổng chi phí đầy đủ**: runner hiện không giữ usage của exception bị cắt, và lần bị gián đoạn có usage không rõ. Cached input và reasoning đã nằm trong các tổng tương ứng, không cộng thêm. Cần lưu usage cả khi lỗi trước khi báo cáo chi phí đầy đủ.

Không ghi DB runtime, không migrate, không gọi Discord hoặc kiểm tra outbox trong lượt live này. Memory được kiểm tra bằng reducer trên kết quả Meta thật; persistence vẫn dựa vào integration tests offline đã ghi ở trên. 8/9 chỉ là mức hoàn tất/khớp nhãn của nhóm ca nhỏ này, **không phải accuracy trên Discord thực tế**. Không trộn lượt chẩn đoán khác effort vào điểm lượt chính.

Artifacts: [input snapshots](evaluations/2026-11-04-v4-meta-cases.jsonl), [predictions chính](evaluations/2026-11-04-v4-meta-predictions.jsonl), [báo cáo chính](evaluations/2026-11-04-v4-meta.json), [prediction memory minimal](evaluations/2026-11-04-v4-meta-memory-minimal-predictions.jsonl), [báo cáo memory minimal](evaluations/2026-11-04-v4-meta-memory-minimal.json). Báo cáo có version/config và hash fixture; đã chấm lại predictions offline mà không gọi thêm API.
