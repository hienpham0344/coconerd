# Kiến trúc backend

Backend là modular monolith: một codebase, API và worker chạy thành hai tiến trình, dùng chung database. Nghiệp vụ được chia thành module có service, persistence port và router tương ứng. Discord bot do ứng dụng bên ngoài đảm nhiệm.

## Tra cứu theo nghiệp vụ

| Nghiệp vụ | HTTP | Use case | Persistence |
| --- | --- | --- | --- |
| Nhận và phân loại message | `routers/messages.py` | `services/messages.py` | `repositories/messages.py`, `jobs.py` |
| Topic, message theo topic, summary và vòng đời | `routers/topics.py` | `services/topics.py` | `repositories/topics.py`, `summaries.py` |
| Review, sửa topic và đối chiếu Discord | `routers/reviews.py` | `services/message_review.py`, `review_operations.py`, `review_audit.py` | `repositories/reviews.py`, `review_queries.py`, `action_recovery.py` |
| Claim và ACK action | `routers/actions.py` | `services/actions.py` | `repositories/actions.py` |
| Guild, channel allowlist và xóa dữ liệu | `routers/guilds.py` | `services/guilds.py` | `repositories/guilds.py` |
| Cấu hình model | `routers/model_config.py` | `services/model_config.py` | `repositories/model_config.py` |
| Health và heartbeat | `routers/health.py` | `services/health.py` | `repositories/health.py` |
| Job, retry và retention | worker | `services/jobs.py`, `retention.py` | `repositories/jobs.py`, `retention.py` |

Các đường dẫn trong bảng lần lượt thuộc `backend/presentation/api/`, `backend/application/` và `backend/infrastructure/database/`.

## Hướng phụ thuộc

```text
HTTP router / worker
        ↓
Application service → persistence Protocol + DTO → domain
        ↑                         ↑
        └──── composition ────────┤
                     SQLAlchemy Unit of Work → repository → SQLite
```

- `backend/domain`: entity, enum và quy tắc chuyển trạng thái; không phụ thuộc framework.
- `backend/application/services`: thực thi nghiệp vụ, chọn chính sách retry/retention, phối hợp repository và quyết định commit. Dùng `ports/persistence.py`, `read_models.py` và domain; không dùng ORM hay HTTP exception.
- `backend/application/agent_workflow.py`, `topic_retriever.py`, `contracts.py`: quy trình AI, bộ lọc local và hợp đồng model. `ModelProvider` là port cho adapter Meta/mock.
- `backend/infrastructure/database`: SQLAlchemy, SQL, ánh xạ ORM sang DTO và Unit of Work. Repository thực hiện truy vấn/thay đổi dữ liệu; service sở hữu commit.
- `backend/presentation/api/routers`: nhận request, kiểm tra dữ liệu HTTP, gọi service và tạo response. Typed application errors được ánh xạ sang mã HTTP tại API boundary.
- `backend/presentation/api/app.py`: tạo ứng dụng, lifespan, middleware, shared dependencies và ghép router. Dependency wiring và `backend/worker.py` tạo session/UoW cụ thể.
- `backend/worker.py`: vòng lặp polling, lịch maintenance, stop và vòng đời provider. Worker gọi các use case cho claim, xử lý, retry, heartbeat và dọn dữ liệu.

Khi thêm nghiệp vụ, đặt chính sách trong service, bổ sung port/DTO cần thiết, triển khai SQL trong repository rồi gọi service từ entrypoint. Không trả ORM record ra ngoài persistence adapter.

## Quyền sở hữu transaction

1. **Ingest:** kiểm tra allowlist rồi lưu message và processing job, commit cùng transaction. Khóa duy nhất `(guild_id, discord_message_id)` chống delivery trùng.
2. **Claim job/action:** ghi lease và attempt rồi commit trước khi thực hiện công việc bên ngoài. Action chỉ đủ điều kiện khi dependency thành công.
3. **Phân loại:** chuẩn bị candidate và gọi provider trước khi staging các thay đổi phân loại. Topic, episode, association, AI decision, summary và outbox action được commit cùng việc hoàn tất job. Nếu xử lý hoặc hoàn tất job thất bại, session rollback toàn bộ thay đổi đó; retry được ghi trong transaction riêng.
4. **Admin, ACK và maintenance:** service commit sau thao tác thành công. Repository không tự commit. Đọc và ACK lặp với cùng kết quả không tạo commit bổ sung.

Unit of Work dùng session SQLAlchemy của entrypoint; repository chỉ trả DTO/plain data. Outbox bảo đảm action Discord được lưu cùng thay đổi topic/summary. Bot dùng `action_id` làm idempotency key, thực thi Discord SDK rồi ACK qua HTTP.

## API và database ở đâu?

Chạy tại thư mục gốc repository:

```bash
alembic upgrade head
organizer-api
# Terminal khác, cùng thư mục và cấu hình:
organizer-worker
```

API mặc định ở `http://localhost:8000`, Swagger ở `/docs`, OpenAPI ở `/openapi.json`. Các endpoint giữ prefix `/api/v1`; chi tiết ở [API contract](API_CONTRACT.md).

`COCONERD_DATABASE_URL` mặc định là `sqlite+aiosqlite:///./data/coconerd.db`: file `data/coconerd.db` tương đối với thư mục chạy lệnh. API, worker và Alembic phải trỏ vào cùng database. Có thể đặt URL tuyệt đối như `sqlite+aiosqlite:////absolute/path/coconerd.db` để tránh phụ thuộc thư mục chạy. Không lưu dữ liệu nghiệp vụ trong RAM của API.

Schema nằm ở `backend/infrastructure/database/models.py`, migration ở `alembic/`; xem [schema dữ liệu](DATA_SCHEMA.md). Ứng dụng không tự migrate khi startup. Connection bật SQLite foreign keys; refactor này không đổi bảng, migration hay engine.

## Vận hành

API key bot và admin được so sánh constant time, dùng header riêng. Guild phải bật rõ channel allowlist. Rate-limit key lưu fingerprint SHA-256. Middleware giới hạn request và gắn request ID; nội dung message không được ghi vào log.

Worker dùng lease có hạn, attempt budget và backoff cho job/action. Khi hết retention, worker xóa message cùng dữ liệu phụ thuộc, bỏ tham chiếu nguồn khỏi summary và loại nội dung nguồn trong action liên quan. Topic `ACTIVE` quá thời gian inactivity trở thành `DORMANT` và kết thúc episode đang mở; đóng `CLOSED` cần admin. Guild model override được ưu tiên trước global/default theo chính sách selector.

SQLite phù hợp triển khai một host với file trên local storage và số lượng ghi đồng thời nhỏ. Cần chọn database/queue phù hợp trước khi mở rộng nhiều host. Health phản ánh kết nối DB và heartbeat gần nhất, không chứng minh mọi job đang tiến triển.

Chất lượng phân loại cần dữ liệu gán nhãn và đánh giá riêng; mock không đo chất lượng Meta. Các giới hạn kiểm chứng hiện tại được ghi trong [tài liệu kiểm thử](TESTING.md).

## Tách trách nhiệm trong đợt reliability

`services/messages.py` giữ ingestion và điều phối phân loại. `topic_memory.py` là reducer thuần cho facts; `services/topic_projection.py` chịu trách nhiệm summary/outbox. Manual review dùng hợp đồng `review_contracts.py`, port riêng `ports/reviews.py` và service riêng, không nhét endpoint/admin logic vào workflow AI.

Các pattern đang dùng là Repository, Unit of Work, Transactional Outbox, provider adapter và optimistic concurrency. Thêm module vì có trách nhiệm nghiệp vụ cụ thể; chưa cần microservices hay một framework subagent mới. Các application/domain module vẫn không import SQLAlchemy hoặc FastAPI.
