# Discord Conversation Organizer

**Backend độc lập để gom hội thoại Discord theo chủ đề.** API nhận và lưu message trước; worker phân loại, cập nhật topic/summary và tạo action để Discord bot bên ngoài xử lý.

> [!NOTE]
> Repository này chỉ chứa backend. Không có bot, Discord SDK, bot token hay bước đăng nhập Discord. Bot do thành viên khác phát triển sẽ tích hợp qua [HTTP API](docs/API_CONTRACT.md).

```text
Discord bot → Backend API → SQLite job queue → AI worker → Topics, summaries, actions → Discord bot
```

## Nội dung

- [Chạy nhanh](#chạy-nhanh)
- [Tính năng](#tính-năng)
- [Cấu trúc backend và lưu trữ](#cấu-trúc-backend-và-lưu-trữ)
- [Tích hợp bot](#tích-hợp-bot)
- [Cấu hình](#cấu-hình)
- [API chính](#api-chính)
- [Kiểm tra và đánh giá](#kiểm-tra-và-đánh-giá)
- [Tài liệu](#tài-liệu)
- [Lưu ý triển khai](#lưu-ý-triển-khai)

## Chạy nhanh

**Yêu cầu:** Python 3.12 trở lên. Cần Meta Model API key để chạy model thật; mock mode chạy offline.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
if [ ! -f .env ]; then cp .env.example .env; fi
```

Trong `.env`, đặt hai giá trị ngẫu nhiên, riêng biệt cho `COCONERD_BOT_API_KEY` và `COCONERD_ADMIN_API_KEY`. Chỉnh `COCONERD_MODEL_API_KEY` nếu dùng model thật. Không commit `.env`.

Chạy các lệnh từ thư mục gốc của cùng một bản checkout. Backend đọc `.env` trong **thư mục chạy lệnh**; `.env.example` chỉ là mẫu, không được tự nạp và không dùng để lưu key thật. Mỗi worktree có file riêng, nên API và worker cần chạy từ cùng checkout để dùng chung cấu hình và đường dẫn SQLite. Sau khi sửa `.env`, khởi động lại tiến trình đang chạy. Kiểm thử riêng Meta không cần bot/admin key.

Khởi tạo database và chạy API:

```bash
alembic upgrade head
organizer-api
```

Mở terminal khác để chạy worker:

```bash
source .venv/bin/activate
organizer-worker
```

API mặc định ở `http://localhost:8000`; Swagger UI ở `/docs`, OpenAPI JSON ở `/openapi.json`. API trả `202 Accepted` sau khi message và job đã commit; worker xử lý message sau đó.

### Chạy offline bằng mock

Trong `.env` đặt:

```dotenv
COCONERD_APP_ENV=development
COCONERD_MOCK_LLM=true
```

Mock chỉ chạy trong môi trường `development` hoặc `test`. Nó giúp kiểm thử luồng tích hợp, không mô phỏng chất lượng Meta và không tạo kết quả benchmark.

## Tính năng

- **Ingest bền vững:** lưu message và job trong cùng transaction; delivery trùng không tạo bản ghi hoặc job mới.
- **Phân nhóm theo topic:** dùng model để chọn topic hiện có, tạo topic mới, defer trường hợp chưa chắc chắn hoặc bỏ qua nội dung không liên quan.
- **Tìm lại topic cũ:** chỉ mục từ khóa trong SQLite, chuẩn hóa dấu và alias; không giới hạn tìm kiếm ở 30 topic gần nhất.
- **Chờ ngữ cảnh:** tin thiếu ngữ cảnh được xét lại tối đa một lần khi có lời giải thích phù hợp; giới hạn hai lượt gọi model cho mỗi message, kể cả lượt lỗi.
- **Memory và summary:** lưu association, episode và các phiên bản summary theo topic.
- **Sửa phân loại có lịch sử:** admin sửa association/summary bằng revision, tạm dừng đồng bộ để đối chiếu Discord và khôi phục action lỗi có audit. Xem [hướng dẫn review](docs/MANUAL_REVIEW.md).
- **Outbox cho Discord:** ghi action cùng transaction với cập nhật topic; bot claim, thực thi và ACK action qua API.
- **Vận hành an toàn hơn:** API key riêng cho bot/admin, allowlist guild/channel, rate limit, giới hạn request, retry có giới hạn và retention dữ liệu.

## Cấu trúc backend và lưu trữ

Xem [báo cáo năng lực, điểm yếu và mức độ hoàn thiện](docs/BACKEND_READINESS.md).

Backend là một ứng dụng chia theo nghiệp vụ: `messages`, `topics`, `actions`, `reviews`, `guilds`, `model_config` và `health`. HTTP và worker gọi cùng lớp use case; persistence được truy cập qua repository và Unit of Work.

```text
backend/
├── domain/                         # Entity và quy tắc vòng đời topic
├── application/
│   ├── services/                   # Use case theo nghiệp vụ
│   ├── ports/persistence.py        # Interface repository và Unit of Work
│   └── read_models.py              # DTO độc lập với database/HTTP
├── infrastructure/database/
│   ├── repositories/              # SQL và ánh xạ ORM → DTO
│   ├── unit_of_work.py             # Quản lý transaction
│   └── models.py                   # Schema SQLAlchemy
├── presentation/api/
│   ├── routers/                   # Endpoint theo nghiệp vụ
│   └── app.py                     # Khởi tạo API và ghép router
└── worker.py                      # Vòng lặp xử lý job và lịch bảo trì
```

**API:** chạy bằng `organizer-api`, mặc định ở `http://localhost:8000`; xem endpoint tại `/docs`. **Database:** SQLite mặc định ở `data/coconerd.db`, tính từ thư mục chạy lệnh. `alembic upgrade head` tạo/cập nhật bảng. API và worker phải dùng cùng `COCONERD_DATABASE_URL` để cùng đọc message, job, topic và action; restart tiến trình không xóa dữ liệu.

Xem [kiến trúc backend](docs/BACKEND_ARCHITECTURE.md) để tra module, transaction và cách mở rộng nghiệp vụ.

## Tích hợp bot

1. Admin bật guild và allowlist channel bằng `PUT /api/v1/admin/guilds/{guild_id}/settings`.
2. Bot gửi message đến `POST /api/v1/messages` với header `X-API-Key`. Gửi Discord message ID, guild/channel, tác giả, nội dung và timestamp có timezone; reply có thể kèm `reply_to_message_id`.
3. Backend lưu message/job và trả `202`; bot không phải chờ model phân loại.
4. Worker chọn ngữ cảnh giới hạn từ các message trước đó cùng guild/kênh (ưu tiên chuỗi reply), phân loại từng message riêng và ghi action cần thực hiện vào outbox.
5. Bot định kỳ gọi `POST /api/v1/actions/claim`, thực thi action bằng Discord API rồi báo kết quả qua `/complete` hoặc `/fail`, kèm `lease_token` nhận từ claim.
6. Bot có thể đọc topic, message và summary để hỗ trợ giao diện riêng.

**Xử lý lặp:** dùng `action_id` làm idempotency key. Action phụ thuộc vào việc tạo thread chỉ được claim sau khi action tạo thread thành công. Payload có thể chứa bản sao message nguồn; bot nên ghi tên tác giả, thời gian và liên kết về message gốc. Discord không thể chuyển message gốc vào thread.

Bot nên gửi từng message gốc ngay khi nhận được và thử lại với cùng `message_id` nếu chưa thấy `202`. Server tự chọn tối đa 6 message ngữ cảnh (chuỗi reply tối đa 3 cấp, phần còn lại trong 10 phút gần nhất), giới hạn 400 ký tự/message và 1.600 ký tự tổng. Các message lân cận có thể thuộc chủ đề khác; AI chỉ quyết định cho message hiện tại. API hiện nhận một message/request và tính rate limit theo từng request; chưa có HTTP batch hay cơ chế chờ gom message.

## Cấu hình

Backend ưu tiên biến `COCONERD_*`; một số tên cũ vẫn được nhận để tương thích. `.env.example` giữ cấu hình mẫu có sẵn của workspace và bổ sung các biến cho backend này.

<details>
<summary>Hiện cấu hình và giá trị mặc định</summary>

| Biến | Mặc định | Mục đích |
| --- | --- | --- |
| `COCONERD_APP_ENV` | `development` | Mock chỉ khả dụng ở `development`/`test` |
| `COCONERD_HOST` / `COCONERD_PORT` | `0.0.0.0` / `8000` | Địa chỉ API bind |
| `COCONERD_DATABASE_URL` | `sqlite+aiosqlite:///./data/coconerd.db` | SQLite async database |
| `COCONERD_BOT_API_KEY` | Chưa đặt | Key riêng cho API bot |
| `COCONERD_ADMIN_API_KEY` | Chưa đặt | Key riêng cho API admin |
| `COCONERD_MODEL_API_KEY` | Chưa đặt | Credential gọi Meta Model API |
| `COCONERD_META_API_BASE` | `https://api.meta.ai/v1` | API base URL |
| `COCONERD_META_MODEL_NAME` | `muse-spark-1.3` | Model ID mặc định |
| `COCONERD_MOCK_LLM` | `false` | Bật provider mock khi phát triển/kiểm thử |
| `COCONERD_WORKER_POLL_SECONDS` | `1` | Thời gian chờ khi không có job |
| `COCONERD_WORKER_LEASE_SECONDS` | `60` | Thời hạn lease cho job |
| `COCONERD_WORKER_MAX_ATTEMPTS` | `5` | Số lần xử lý job tối đa |
| `COCONERD_ACTION_LEASE_SECONDS` | `60` | Thời hạn bot giữ action |
| `COCONERD_MAX_REQUEST_BYTES` | `65536` | Giới hạn kích thước request |
| `COCONERD_MAX_MESSAGE_LENGTH` | `8000` | Giới hạn nội dung một message |
| `COCONERD_RETENTION_DAYS` | `365` | Retention mặc định cho guild |
| `COCONERD_TOPIC_DORMANT_AFTER_DAYS` | `30` | Số ngày trước khi topic inactive thành dormant |

Các biến `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `COCONERD_CORS_ORIGINS` và `COCONERD_LOG_LEVEL` được mô tả trong [cấu hình model](docs/MODEL_CONFIGURATION.md) và file mẫu.

</details>

## API chính

Bot dùng `X-API-Key`; admin dùng key riêng `X-Admin-API-Key`. Topic read luôn cần `guild_id`; ID thuộc guild khác trả `404`.

<details>
<summary>Hiện danh sách endpoint chính</summary>

| Method | Path | Quyền | Mục đích |
| --- | --- | --- | --- |
| `POST` | `/api/v1/messages` | Bot | Ingest message và enqueue job |
| `POST` | `/api/v1/actions/claim` | Bot | Claim action sẵn sàng xử lý |
| `POST` | `/api/v1/actions/{action_id}/complete` | Bot | ACK action thành công |
| `POST` | `/api/v1/actions/{action_id}/fail` | Bot | Báo lỗi để retry hoặc kết thúc action |
| `GET` | `/api/v1/topics/{topic_id}` | Bot | Đọc topic trong guild |
| `GET` | `/api/v1/topics/{topic_id}/messages` | Bot | Đọc message theo trang |
| `GET` | `/api/v1/topics/{topic_id}/summary` | Bot | Đọc summary mới nhất |
| `PUT` | `/api/v1/admin/guilds/{guild_id}/settings` | Admin | Cấu hình guild, channel allowlist, retention |
| `PUT` / `GET` | `/api/v1/admin/model-config` | Admin | Cấu hình model toàn cục hoặc theo guild |
| `POST` | `/api/v1/admin/topics/{topic_id}/close` | Admin | Đóng topic rõ ràng |
| `GET` | `/api/v1/health` | Public | Kiểm tra database và heartbeat worker |

</details>

Request/response, headers, rate limit và mã lỗi được mô tả trong [API contract](docs/API_CONTRACT.md). Các endpoint admin khác gồm đóng/xóa topic và xóa dữ liệu guild.

## Kiểm tra và đánh giá

```bash
pytest
ruff check backend tests scripts alembic
ruff format --check backend tests scripts alembic
```

Suite dùng SQLite cục bộ và provider mock, không gọi Meta API có tính phí. Fixture trong `tests/fixtures/evaluation/` là dữ liệu tổng hợp nhỏ, không đại diện benchmark. Cách chạy metric trên prediction xem [tài liệu kiểm thử](docs/TESTING.md).

## Phân loại topic

Backend hợp nhất tối đa 30 topic từ chỉ mục tìm kiếm với 30 topic gần đây trong cùng guild, xếp hạng cục bộ và gửi tối đa 5 topic gọn cho Meta. Topic cũ còn mở vẫn có thể được tìm thấy. Context giới hạn 6 tin/1.600 ký tự; reply và lời giải thích được ưu tiên, nhưng không tự động chứng minh cùng topic.

Policy `topic-policy-v4` yêu cầu evidence chứa ID tin gốc, chỉ dùng ID đã cung cấp và topic nằm trong shortlist. Input nhiều chủ đề được `defer`; title trùng không tự ép gộp. Backend kiểm tra lại trạng thái topic trước khi ghi association/summary/action. Assignment dưới confidence 0.7 được defer. Memory giữ facts cũ và chỉ cho thay/xóa bằng tham chiếu/quote hợp lệ. Kiểm tra ID không chứng minh model hiểu đúng nghĩa; confidence chưa được hiệu chỉnh thành xác suất đúng.

Tin rỗng thành `irrelevant`; câu xác nhận như `ok` không có điểm tham chiếu thành `defer`, đều không gọi Meta. Tin `defer` vì thiếu ngữ cảnh hoặc mơ hồ có thể chờ lời giải thích cùng channel trong 10 phút và xét lại một lần. Association đã gán topic không tự đổi. Mỗi message được đặt chỗ tối đa hai lượt gọi model qua mọi lần retry; lỗi hoặc crash sau đặt chỗ vẫn có thể tiêu hao hạn mức.

Mặc định dùng `COCONERD_LLM_REASONING_EFFORT=low` và `COCONERD_LLM_MAX_TOKENS=2048`. Prompt có tiền tố/cache key theo phiên bản; token thiếu thông tin giữ giá trị chưa biết. Tools là các hàm đọc dữ liệu do code điều phối, chưa thêm model subagent hoặc vector DB. Bộ đánh giá có dev/holdout tổng hợp, chế độ mock và live có giới hạn lượt gọi; xem [cách chạy và giới hạn kết luận](docs/TESTING.md).

## Tài liệu

| Tài liệu | Nội dung |
| --- | --- |
| [API contract](docs/API_CONTRACT.md) | Tích hợp bot/admin, schema và mã lỗi |
| [Kiến trúc](docs/BACKEND_ARCHITECTURE.md) | Ranh giới thành phần và độ tin cậy |
| [Schema dữ liệu](docs/DATA_SCHEMA.md) | Các bảng và quan hệ persistence |
| [Agent workflow](docs/AGENT_WORKFLOW.md) | Quy trình phân loại và cập nhật topic |
| [Cấu hình model](docs/MODEL_CONFIGURATION.md) | Provider, model và cấu hình override |
| [Kiểm thử](docs/TESTING.md) | Test suite và công cụ đánh giá |

## Lưu ý triển khai

- Chạy `alembic upgrade head` trước khi khởi động API/worker; ứng dụng không tự tạo hoặc migrate schema khi startup.
- SQLite phù hợp cho local hoặc một host dùng file local. Trước khi chạy nhiều host hay tăng tải ghi đồng thời, cần chuyển sang database/queue phù hợp.
- Nếu bot ở máy khác, giới hạn cổng API bằng firewall cho host đó và dùng TLS qua reverse proxy. Không expose API công khai bằng HTTP không bảo vệ.
- Health endpoint báo trạng thái database và heartbeat worker gần nhất; nó không đo tiến triển của từng job.
- Message tuân theo retention của guild. Cấu hình chính sách lưu trữ phù hợp trước khi ingest.
