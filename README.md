# Coconerd

**Website:** [coconerd-2bn1.vercel.app](https://coconerd-2bn1.vercel.app/)

**Bot Discord, backend tổ chức hội thoại và website công khai trong cùng repository.** API nhận và lưu message trước; worker phân loại, cập nhật topic/summary và tạo action để bot xử lý.

> [!NOTE]
> `backend/` chứa API và worker Python; `bot/` chứa bot Discord; `web/` chứa website React/TypeScript và máy chủ web Node.js. Trang công khai/demo không yêu cầu đăng nhập. Dashboard thật tại `/#/app` yêu cầu Discord OAuth và quyền owner/Administrator của từng server; xem cấu hình trong [web/README.md](web/README.md). Các thành phần vẫn chạy và triển khai độc lập. Hợp đồng tích hợp bot nằm trong [HTTP API](docs/API_CONTRACT.md).

```text
Discord bot → Backend API → Railway PostgreSQL → AI worker → Topics, summaries, actions → Discord bot
```

## Website công khai

Cần Node.js 22.12 trở lên. Từ thư mục gốc repo:

```bash
cd web
npm ci
npm run dev
```

Mở http://127.0.0.1:5173/. Website và dữ liệu mẫu hoạt động độc lập với bot/backend; không cần `.env` để xem thử. Hướng dẫn link Discord, health, production build và kiểm tra nằm trong [web/README.md](web/README.md).

```text
coconerd/
├── backend/       # API và worker Python
├── bot/           # Discord bot
├── web/           # Website, server Node.js và test riêng
├── alembic/       # Migration backend
├── tests/         # Test backend
├── scripts/
├── docs/
└── pyproject.toml
```

Kiểm tra website bằng `npm test` và `npm run build` trong `web/`; kiểm tra backend bằng `python -m pytest -q` từ gốc repo. Bridge nội bộ tùy chọn có test riêng: `cd web && npm run test:bridge`. Không đưa `.env`, `node_modules`, build output, cache hoặc database vào Git.

## Bắt đầu từ đâu?

- **Cài backend, tạo DB, chạy API/worker:** [Setup backend và database](docs/BACKEND_SETUP.md).
- **Gắn bot vào backend:** [Hướng dẫn tích hợp Discord bot](docs/BOT_INTEGRATION.md).
- **Tra JSON, endpoint và lỗi:** [API contract](docs/API_CONTRACT.md); khi API chạy, mở [Swagger UI](http://127.0.0.1:8000/docs).
- **Đọc code hoặc mở rộng:** [Kiến trúc và trách nhiệm module](docs/BACKEND_ARCHITECTURE.md).

## Chạy local

Yêu cầu Python **3.12+**, Git; các ví dụ HTTP dùng `curl`. Chạy lệnh tại thư mục gốc checkout:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
if [ ! -f .env ]; then cp .env.example .env; fi
```

Sửa `.env`: đặt Railway PostgreSQL URL theo [hướng dẫn database](docs/RAILWAY_POSTGRES.md), cùng hai key ngẫu nhiên, khác nhau cho `COCONERD_BOT_API_KEY` và `COCONERD_ADMIN_API_KEY`. `COCONERD_REQUIRE_POSTGRES=true` chặn việc dùng nhầm SQLite. Để kiểm tra model bằng mock, giữ `COCONERD_MOCK_LLM=true`, `COCONERD_APP_ENV=development`. File mẫu không chứa credential thật; không commit `.env`.

```bash
mkdir -p data
alembic upgrade head
alembic current
organizer-api
```

Terminal thứ hai, **cùng checkout**:

```bash
source .venv/bin/activate
organizer-worker
```

Terminal thứ ba:

```bash
curl --fail-with-body --silent --show-error http://127.0.0.1:8000/api/v1/health
```

Khi API kết nối DB và worker có heartbeat, kết quả là `{"status":"ok","database":"ok","worker":"ok"}`. Health có thể trả HTTP 200 với `status=degraded`; cần đọc JSON. Tiếp theo [bật guild/channel và gửi message thử](docs/BACKEND_SETUP.md#5-bật-guildchannel-và-gửi-message-thử).

Muốn dùng Meta thật: đặt `COCONERD_MODEL_API_KEY`, đổi `COCONERD_MOCK_LLM=false`, restart worker. Cấu hình mặc định: `muse-spark-1.3`, effort `low`, tối đa 2.048 output tokens/call. Xem [cấu hình model](docs/MODEL_CONFIGURATION.md), gồm override theo guild.

Router task mặc định bật bằng `COCONERD_AGENT_MODE=task`: tách `chat`,
`topic_classification`, `topic_memory` với profile riêng, deadline và giới hạn input/output.
Đặt `COCONERD_TASK_PROFILES` bằng JSON để cấu hình từng task; `single` dùng thông số base.
Phân loại và cập nhật memory vẫn dùng chung một lượt Meta; xem [hướng dẫn điều phối task](docs/TASK_ORCHESTRATION.md).

## Chạy Discord bot

```bash
python -m pip install -r bot/requirements.txt
python -m bot.main
```

Đặt `DISCORD_BOT_TOKEN`, `BACKEND_BASE_URL`, `COCONERD_BOT_API_KEY` và
`COCONERD_ADMIN_API_KEY` trong `.env`. API và worker phải chạy riêng. Mọi tính năng
AI đều dùng Meta: chat khi tag bot, phân loại topic và cập nhật summary/memory.
Chat và worker dùng chung `COCONERD_MODEL_API_KEY`, `COCONERD_META_MODEL_NAME`
(mặc định `muse-spark-1.3`), `COCONERD_LLM_REASONING_EFFORT` và `COCONERD_LLM_MAX_TOKENS`.
`COCONERD_MOCK_LLM=true` chỉ giả lập worker khi test offline; chat cần key Meta thật.
Khi thiếu key, Meta lỗi hoặc phản hồi quá hạn, chat dùng câu meme tĩnh có sẵn,
không chuyển sang model khác. Package `openai` chỉ làm SDK tương thích để gọi
`https://api.meta.ai/v1`; không dùng model OpenAI. Sau khi sửa `.env`, restart bot và worker.
Quản trị viên dùng `/setup` để chọn các Input Channel và một Output Channel riêng.
Bot tự đăng tiêu đề topic vào Output Channel, tạo Thread gắn với tin tiêu đề,
rồi sao chép tin thành viên vào Thread theo dạng `[tên]-tin nhắn`.
Chỉ nội dung đáng ghi nhớ mới tạo/cập nhật topic: thảo luận có thông tin, lịch họp/học,
ăn uống, đề xuất, quyết định và việc cần làm. Chào hỏi, đùa và chuyện phiếm được bỏ qua;
câu hỏi thực tế chưa có câu trả lời vẫn được giữ. AI phân biệt theo ngữ cảnh, không chỉ từ khóa.
Tin đầu trong Output Channel có ghi chú tự cập nhật, tách nội dung chính, đề xuất,
điều đã chốt, việc cần làm và câu hỏi còn mở; tin gốc được giữ trong Thread để đối chiếu.
Gọi `/summarize` ngay trong Thread để đăng thêm bản tóm tắt, không cần nhập số topic.
Khi đổi Output Channel, action tiếp theo sẽ tạo Thread tại nơi mới và sao chép lịch sử.
Bot lưu receipt qua HTTP API vào bảng `delivery_receipts` trong cùng PostgreSQL;
không tạo database SQLite riêng. Backend/DB lỗi thì delivery dừng để retry.
Dùng `/summarize topic_id:0` để xem danh sách topic trong Input Channel;
`/summarize topic_id:1` xem và xuất summary của topic đầu tiên.

Database cũ cần chạy `alembic upgrade head` trước khi khởi động API/worker mới.
Migration bổ sung cấu hình Output Channel và backfill channel gốc của topic.

## Cấu trúc repository

```text
.
├── backend/
│   ├── domain/                     # Entity, enum, vòng đời topic
│   ├── application/
│   │   ├── services/               # Ingest, topic, action, review, job
│   │   ├── ports/                  # Hợp đồng persistence/review
│   │   ├── data/                   # Dữ liệu chuẩn hóa ngôn ngữ
│   │   ├── agent_workflow.py       # Điều phối phân loại và evidence
│   │   └── topic_memory.py         # Gộp/sửa facts trong memory
│   ├── infrastructure/
│   │   ├── database/               # ORM, repository, Unit of Work
│   │   └── meta_provider.py        # Adapter Meta và mock
│   ├── presentation/api/           # FastAPI, auth, schema, router
│   ├── config.py                   # Đọc cấu hình từ environment/.env
│   └── worker.py                   # Job polling, retry, maintenance
├── bot/                           # Discord bot và slash commands
├── web/                           # Website React và server Node.js
├── alembic/versions/               # Migration có version
├── data/                          # SQLite runtime, không commit DB
├── docs/                          # Setup, tích hợp, kiến trúc, đánh giá
├── scripts/                       # CLI đánh giá agent/grouping
├── tests/backend/                 # Unit, repository, API, integration
├── tests/fixtures/evaluation/      # Hội thoại tổng hợp có nhãn
├── .env.example                   # Mẫu cấu hình
└── pyproject.toml                 # Dependency, entrypoint, pytest, Ruff
```

Router gọi application service; service dùng port/DTO; infrastructure triển khai SQL và transaction. API và worker dùng chung nghiệp vụ, cùng DB. Các ranh giới này được kiểm tra bằng `tests/backend/test_architecture.py`; xem [kiến trúc](docs/BACKEND_ARCHITECTURE.md) và [schema](docs/DATA_SCHEMA.md).

## Những việc backend xử lý

- Lưu message/job cùng transaction, chống delivery trùng theo `(guild_id, message_id)`.
- Tìm topic cũ trong cùng guild bằng chỉ mục local, gửi tối đa 5 ứng viên cho model.
- Kết quả `new`, `existing`, `defer` hoặc `irrelevant`; giữ tối đa 6 message ngữ cảnh/1.600 ký tự.
- Memory có phiên bản; thay/xóa fact cần tham chiếu fact cũ và quote nguồn hợp lệ.
- Chờ clarification và xét lại tối đa một lần; tối đa hai reservation gọi model/message qua mọi retry.
- Outbox có lease/token, retry/backoff; action cùng topic được xử lý tuần tự.
- Admin review/correction có revision, audit, pause/resume sync và recovery.

## Hợp đồng cần thống nhất với bot

1. Admin bật guild và allowlist channel bằng key admin.
2. Bot gửi từng message gốc đến `POST /api/v1/messages` với `X-API-Key`.
3. `202` xác nhận đã lưu; worker phân loại sau đó. `defer`/`irrelevant` có thể không sinh action.
4. Bot poll `POST /api/v1/actions/claim`, thực hiện action, rồi `/complete` hoặc `/fail` với đúng `worker_id` và `lease_token`.
5. Bot lưu receipt bền vững cho tiêu đề, Thread, từng tin nguồn/phần tin và summary; retry dùng lại ID đã lưu. Vẫn có cửa sổ crash giữa Discord request và ghi receipt.

**Backend không gửi Discord request.** Bot tự xử lý quyền, Discord rate limit, định dạng nội dung và chống vòng lặp ingest message do chính bot gửi. Ví dụ đầy đủ, lease và checklist pilot nằm trong [BOT_INTEGRATION.md](docs/BOT_INTEGRATION.md).

## Cấu hình thiết yếu

| Biến | Vai trò |
| --- | --- |
| `COCONERD_DATABASE_URL` | Mặc định `sqlite+aiosqlite:///./data/coconerd.db` |
| `COCONERD_BOT_API_KEY` | Key backend dành cho bot, khác Discord token |
| `COCONERD_ADMIN_API_KEY` | Key cấu hình/review; giữ ở phía quản trị |
| `COCONERD_MOCK_LLM` | Code mặc định `false`; file mẫu đặt `true` để chạy offline |
| `COCONERD_MODEL_API_KEY` | Key Meta khi tắt mock |
| `COCONERD_HOST` / `COCONERD_PORT` | Mặc định `0.0.0.0:8000`; local có thể bind `127.0.0.1` |
| `COCONERD_ACTION_LEASE_SECONDS` | Mặc định 60 giây để bot thực thi và ACK |

`Settings` đọc `.env` theo **thư mục chạy lệnh**. Environment có độ ưu tiên cao hơn, kể cả giá trị rỗng. API, worker và Alembic cần cùng checkout/DB URL; `.env` không tự được export vào shell. Tra toàn bộ mẫu tại [.env.example](.env.example).

## Kiểm tra

```bash
pytest -q --tb=short
ruff check backend tests scripts alembic
ruff format --check backend tests scripts alembic
```

Suite offline không gọi Meta/Discord thật. Mốc kiểm chứng ngày 2026-11-04: **250 test passed**; test tích hợp dùng DB migrate tạm và bot giả lập. Đây không phải bảo đảm accuracy, tải production hoặc tích hợp Discord thực tế. Xem [kết quả và giới hạn kiểm thử](docs/TESTING.md).

## Tài liệu và vận hành

- [Setup backend/DB](docs/BACKEND_SETUP.md): môi trường, migration, backup, health và xử lý lỗi.
- [Tích hợp bot](docs/BOT_INTEGRATION.md) · [API contract](docs/API_CONTRACT.md).
- [Kiến trúc](docs/BACKEND_ARCHITECTURE.md) · [Schema dữ liệu](docs/DATA_SCHEMA.md).
- [Agent workflow](docs/AGENT_WORKFLOW.md) · [Model configuration](docs/MODEL_CONFIGURATION.md).
- [Manual review](docs/MANUAL_REVIEW.md) · [Readiness và hạn chế](docs/BACKEND_READINESS.md).

Runtime hiện dùng Railway PostgreSQL với `COCONERD_REQUIRE_POSTGRES=true`, từ chối cấu hình SQLite. SQLite vẫn dùng cho kiểm thử độc lập và bản sao lịch sử. Xem [cấu hình Railway và chuyển lịch sử](docs/RAILWAY_POSTGRES.md). Ứng dụng không tự migrate schema. Chưa có giao thức sửa/xóa message Discord, OCR/attachment extraction, hay bảo đảm exactly-once trên Discord.
