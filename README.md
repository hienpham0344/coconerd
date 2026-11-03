# Discord Conversation Organizer — Backend

Backend Python độc lập để gom hội thoại Discord theo chủ đề. Backend lưu tin nhắn trước, xử lý AI ở worker riêng, duy trì topic và summary, rồi tạo action để một Discord bot bên ngoài thực thi.

> **Phạm vi:** repository này chỉ chứa backend. Không có Discord bot, Discord SDK, token bot hay bước đăng nhập Discord. Bot do thành viên khác phát triển có thể tích hợp qua HTTP API trong [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md).

## Chức năng

- Nhận message từ bot qua API có API key; chỉ chấp nhận guild/channel được admin cho phép.
- Lưu message và processing job trong cùng transaction, hỗ trợ gửi lặp mà không tạo bản ghi/job trùng.
- Phân nhóm message vào topic, tiếp tục topic qua reply, lưu episode, association và phiên bản summary.
- Chạy Meta Model API qua OpenAI-compatible endpoint; hỗ trợ mock cục bộ để phát triển offline.
- Ghi các yêu cầu tạo/cập nhật Discord thread vào transactional outbox. Bot claim action, thực hiện Discord API, rồi báo hoàn tất hoặc lỗi.
- Có lease, retry giới hạn, rate limit, giới hạn kích thước request, retention dữ liệu và endpoint quản trị.

## Yêu cầu

- Python 3.12 trở lên.
- Meta Model API key nếu muốn phân loại bằng model thật. Không cần key để dùng mock mode.

## Cài đặt và chạy local

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
```

`.env.example` giữ lại cấu hình mẫu có sẵn của workspace và bổ sung nhóm biến `COCONERD_*` cho backend này. Chỉnh các giá trị `replace-with-...` trong `.env`; dùng hai API key ngẫu nhiên, riêng biệt cho bot và admin. Không commit `.env`.

Khởi tạo database rồi chạy API:

```bash
alembic upgrade head
organizer-api
```

Chạy worker trong terminal khác:

```bash
source .venv/bin/activate
organizer-worker
```

API mặc định ở `http://localhost:8000`; Swagger UI ở `/docs`, OpenAPI JSON ở `/openapi.json`. API và worker là hai process riêng. API trả `202 Accepted` sau khi message cùng job đã commit; worker xử lý sau đó.

### Chạy mock không cần Meta key

Trong `.env` đặt:

```dotenv
COCONERD_APP_ENV=development
COCONERD_MOCK_LLM=true
```

Mock chạy có chủ đích đơn giản để kiểm thử luồng tích hợp; nó không mô phỏng chất lượng Meta và không phải kết quả benchmark. Mock chỉ được bật trong `development` hoặc `test`.

## Cấu hình

Backend ưu tiên tên biến `COCONERD_*`; một số tên cũ vẫn được nhận để tương thích. Các giá trị mặc định chính:

| Biến | Mặc định | Mục đích |
| --- | --- | --- |
| `COCONERD_APP_ENV` | `development` | Môi trường; mock chỉ khả dụng ở `development`/`test` |
| `COCONERD_HOST` / `COCONERD_PORT` | `0.0.0.0` / `8000` | Địa chỉ API bind |
| `COCONERD_DATABASE_URL` | `sqlite+aiosqlite:///./data/coconerd.db` | SQLite async database |
| `COCONERD_BOT_API_KEY` | chưa đặt | Key riêng cho API của bot |
| `COCONERD_ADMIN_API_KEY` | chưa đặt | Key riêng cho endpoint quản trị |
| `COCONERD_MODEL_API_KEY` | chưa đặt | Credential gọi Meta Model API |
| `COCONERD_META_API_BASE` | `https://api.meta.ai/v1` | API base URL |
| `COCONERD_META_MODEL_NAME` | `muse-spark-1.3` | Model ID mặc định |
| `COCONERD_MOCK_LLM` | `false` | Bật provider mock khi phát triển/kiểm thử |
| `COCONERD_WORKER_POLL_SECONDS` | `1` | Thời gian chờ khi không có job |
| `COCONERD_WORKER_LEASE_SECONDS` | `60` | Thời hạn lease cho job |
| `COCONERD_WORKER_MAX_ATTEMPTS` | `5` | Số lần xử lý tối đa |
| `COCONERD_ACTION_LEASE_SECONDS` | `60` | Thời hạn bot giữ action |
| `COCONERD_MAX_REQUEST_BYTES` | `65536` | Giới hạn kích thước request |
| `COCONERD_MAX_MESSAGE_LENGTH` | `8000` | Giới hạn nội dung một message |
| `COCONERD_RETENTION_DAYS` | `365` | Thời gian lưu message mặc định cho guild |
| `COCONERD_TOPIC_DORMANT_AFTER_DAYS` | `30` | Sau thời gian này topic không hoạt động chuyển sang dormant |

Các biến model khác như `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `COCONERD_CORS_ORIGINS` và `COCONERD_LOG_LEVEL` được mô tả trong [`docs/MODEL_CONFIGURATION.md`](docs/MODEL_CONFIGURATION.md) và file mẫu.

## Luồng tích hợp cho Discord bot

1. Admin gọi `PUT /api/v1/admin/guilds/{guild_id}/settings` để bật guild và allowlist channel.
2. Bot gửi message đến `POST /api/v1/messages` với header `X-API-Key`. Message cần có ID Discord, guild/channel, tác giả, nội dung và timestamp có timezone; reply có thể gửi `reply_to_message_id`.
3. Backend lưu message/job và trả `202`; bot không cần đợi model chạy xong.
4. Worker phân loại message và ghi các action cần thiết vào outbox.
5. Bot định kỳ gọi `POST /api/v1/actions/claim`, thực thi action bằng Discord API, rồi gọi endpoint `/complete` hoặc `/fail` tương ứng.
6. Bot có thể đọc topic, message và summary qua API để hỗ trợ giao diện riêng.

Bot nên coi `action_id` là idempotency key. Action phụ thuộc vào việc tạo thread sẽ chỉ được claim sau khi action tạo thread hoàn tất. Payload action có thể chứa bản sao nội dung message nguồn; bot chỉ nên đăng nội dung được yêu cầu, ghi tác giả/thời gian và liên kết message gốc. Xem schema request/response và mã lỗi tại [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md).

## API chính

| Method | Path | Quyền | Mục đích |
| --- | --- | --- | --- |
| `POST` | `/api/v1/messages` | Bot | Ingest message và enqueue job bền vững |
| `POST` | `/api/v1/actions/claim` | Bot | Claim các action sẵn sàng xử lý |
| `POST` | `/api/v1/actions/{action_id}/complete` | Bot | ACK action đã chạy thành công |
| `POST` | `/api/v1/actions/{action_id}/fail` | Bot | Báo lỗi để retry hoặc kết thúc action |
| `GET` | `/api/v1/topics/{topic_id}` | Bot | Đọc topic trong guild |
| `GET` | `/api/v1/topics/{topic_id}/messages` | Bot | Đọc message theo trang |
| `GET` | `/api/v1/topics/{topic_id}/summary` | Bot | Đọc summary mới nhất |
| `PUT` | `/api/v1/admin/guilds/{guild_id}/settings` | Admin | Cấu hình guild, channel allowlist, retention |
| `PUT` / `GET` | `/api/v1/admin/model-config` | Admin | Cấu hình model toàn cục hoặc theo guild |
| `POST` | `/api/v1/admin/topics/{topic_id}/close` | Admin | Đóng topic rõ ràng |
| `GET` | `/api/v1/health` | Public | Kiểm tra database và heartbeat worker |

Bot dùng `X-API-Key`; admin dùng key riêng `X-Admin-API-Key`. Topic read luôn cần `guild_id`; ID thuộc guild khác trả `404`. API contract đầy đủ có trong [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md).

## Kiểm tra và đánh giá

```bash
pytest
ruff check backend tests scripts
ruff format --check backend tests scripts
```

Kiểm thử dùng SQLite cục bộ và provider mock, không gọi Meta API có tính phí. Bộ fixture tại `tests/fixtures/evaluation/` chỉ là dữ liệu tổng hợp nhỏ, không đại diện benchmark. Cách chạy metric trên nhãn/prediction của bạn xem [`docs/TESTING.md`](docs/TESTING.md).

## Tài liệu

- [API contract cho bot và admin](docs/API_CONTRACT.md)
- [Kiến trúc backend](docs/BACKEND_ARCHITECTURE.md)
- [Schema dữ liệu](docs/DATA_SCHEMA.md)
- [Agent workflow](docs/AGENT_WORKFLOW.md)
- [Cấu hình model](docs/MODEL_CONFIGURATION.md)
- [Kiểm thử và đánh giá](docs/TESTING.md)

## Lưu ý triển khai

- Chạy `alembic upgrade head` trước khi khởi động API/worker; ứng dụng không tự tạo hoặc tự migrate schema lúc startup.
- SQLite phù hợp cho chạy local hoặc một host dùng chung file local. Khi cần nhiều host/ghi đồng thời cao, cần chuyển database/queue phù hợp trước khi scale.
- Nếu bot chạy trên máy khác, giới hạn truy cập cổng API ở firewall cho host đó và dùng TLS qua reverse proxy. Không expose API công khai với HTTP không bảo vệ.
- Health endpoint báo trạng thái database và heartbeat gần nhất của worker; nó không đo mức tiến triển của từng job.
- Dữ liệu hội thoại được lưu theo retention của guild. Hãy cấu hình chính sách lưu trữ phù hợp với server trước khi ingest.
