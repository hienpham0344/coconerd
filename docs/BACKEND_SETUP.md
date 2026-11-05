# Setup backend và database

Hướng dẫn cho Linux/Bash, chạy tại thư mục gốc repository chứa `pyproject.toml` và `alembic.ini`. API và worker là hai tiến trình riêng. Bot Discord là ứng dụng thứ ba, kết nối qua HTTP.

Runtime dùng [Railway PostgreSQL](RAILWAY_POSTGRES.md) với
`COCONERD_REQUIRE_POSTGRES=true`. Các đoạn SQLite bên dưới chỉ dành cho kiểm thử
hoặc dữ liệu local cũ; không dùng để khởi động runtime hiện tại.

## 1. Tạo môi trường Python

Kiểm tra `python3.12 --version` (hoặc Python mới hơn, tối thiểu 3.12), `git --version` và `curl --version`. Nếu lệnh Python trên máy có tên khác, dùng tên đó để tạo venv.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
if [ ! -f .env ]; then cp .env.example .env; fi
```

`.[dev]` gồm pytest, Ruff và HTTPX để kiểm tra tích hợp. Chạy dịch vụ không cần dev tools thì cài `python -m pip install -e .`. Các lệnh `organizer-api`, `organizer-worker`, `alembic` nằm trong `.venv/bin/` sau khi cài.

## 2. Cấu hình `.env`

Điền hai secret ngẫu nhiên riêng biệt, nên có ít nhất 32 ký tự, bằng trình soạn thảo hoặc secret manager:

```dotenv
COCONERD_APP_ENV=development
COCONERD_DEBUG=false
COCONERD_HOST=127.0.0.1
COCONERD_PORT=8000
COCONERD_DATABASE_URL=sqlite+aiosqlite:///./data/coconerd.db
COCONERD_BOT_API_KEY=<bot-backend-key>
COCONERD_ADMIN_API_KEY=<admin-backend-key>
COCONERD_MOCK_LLM=true
```

Thay các placeholder trước khi chạy. Không dùng Discord token làm API key của backend. Không commit `.env` hoặc copy key thật vào `.env.example`.

- `.env` được đọc theo thư mục chạy lệnh; không tự tìm sang checkout/worktree khác.
- Environment có độ ưu tiên cao hơn `.env`, kể cả biến đã export với giá trị rỗng. Nếu giá trị không đúng như dự kiến, kiểm tra hoặc `unset` đúng biến cũ rồi restart dịch vụ.
- Không cần `source .env`; file cấu hình có giá trị JSON và được Pydantic đọc trực tiếp. Các ví dụ `curl` bên dưới nhập key riêng vào biến shell.
- Mock chỉ dùng được trong `development`/`test`. Để dùng Meta thật, đặt `COCONERD_MODEL_API_KEY`, đổi `COCONERD_MOCK_LLM=false`, restart worker. Tham khảo [model configuration](MODEL_CONFIGURATION.md).

## 3. Khởi tạo và kiểm tra database

Backend hiện dùng **SQLite + aiosqlite**, không cần cài một DB server. Tạo thư mục chứa file **trước Alembic**:

```bash
mkdir -p data
alembic upgrade head
alembic current
alembic check
```

`upgrade head` tạo DB mới nếu chưa có, hoặc áp dụng migration còn thiếu. Nó không chạy lại migration đã hoàn tất. Revision hiện tại là `20261104_0003`; `alembic current` phải khớp `alembic heads`. `alembic check` kiểm tra chênh lệch ORM/schema, không kiểm tra dữ liệu nghiệp vụ.

Không chạy `alembic stamp head` để bỏ qua tạo bảng. API/worker không tự migrate; chạy chúng trước migration có thể gặp `no such table`.

### Đường dẫn SQLite

```dotenv
# Tương đối với thư mục chạy lệnh:
COCONERD_DATABASE_URL=sqlite+aiosqlite:///./data/coconerd.db

# Hoặc tuyệt đối, ví dụ minh họa:
COCONERD_DATABASE_URL=sqlite+aiosqlite:////srv/coconerd/data/coconerd.db
```

Nếu dùng đường dẫn riêng, tạo thư mục cha và cấp quyền đọc/ghi cho user chạy dịch vụ. API, worker và Alembic phải trỏ **cùng file**. Giữ file trên local storage của cùng host; cấu hình hiện từ chối URL PostgreSQL/MySQL. Các bảng được mô tả trong [DATA_SCHEMA.md](DATA_SCHEMA.md).

Kiểm tra DB mặc định mà không vô tình tạo file mới:

```bash
python - <<'PY'
import sqlite3
with sqlite3.connect('file:data/coconerd.db?mode=ro', uri=True) as db:
    print('revision:', db.execute('SELECT version_num FROM alembic_version').fetchone()[0])
    print('integrity:', db.execute('PRAGMA integrity_check').fetchone()[0])
    print('foreign_key_violations:', len(db.execute('PRAGMA foreign_key_check').fetchall()))
PY
```

Mong đợi `integrity: ok`, `foreign_key_violations: 0`. Đổi đường dẫn trong snippet nếu dùng DB khác.

### Nâng cấp và sao lưu DB đang có dữ liệu

Tạm dừng ingest/claim ở bot và dừng API/worker trước khi thay schema. Tạo bản backup, kiểm tra lại cấu hình DB, rồi chạy `alembic upgrade head`, `alembic current`, `alembic check` và bật lại dịch vụ.

Ví dụ backup DB mặc định bằng SQLite backup API, giữ nguyên file nguồn:

```bash
python - <<'PY'
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from uuid import uuid4

folder = Path('data/backups')
folder.mkdir(parents=True, exist_ok=True)
stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
target = folder / f'coconerd-{stamp}-{uuid4().hex[:8]}.db'
with sqlite3.connect('file:data/coconerd.db?mode=ro', uri=True) as source:
    with sqlite3.connect(target) as backup:
        source.backup(backup)
        assert backup.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
print(target)
PY
```

Không xóa DB để sửa migration lỗi và không downgrade trên dữ liệu thật khi chưa đánh giá ảnh hưởng. Backup chứa dữ liệu hội thoại, cần bảo vệ như DB gốc; không commit lên Git.

## 4. Chạy API và worker

Terminal A:

```bash
source .venv/bin/activate
organizer-api
```

Terminal B, cùng thư mục và cấu hình:

```bash
source .venv/bin/activate
organizer-worker
```

Terminal C:

```bash
curl --fail-with-body --silent --show-error http://127.0.0.1:8000/api/v1/health
```

Mong đợi khi worker sẵn sàng:

```json
{"status":"ok","database":"ok","worker":"ok"}
```

Nếu chỉ API chạy, có thể nhận `status=degraded`, `worker=unavailable`. Endpoint vẫn trả HTTP 200; health checker cần đọc body. `database=ok` chỉ phản ánh probe kết nối, không thay thế kiểm tra migration hoặc việc từng job đang tiến triển.

Mở [Swagger UI](http://127.0.0.1:8000/docs) hoặc [OpenAPI JSON](http://127.0.0.1:8000/openapi.json). `Ctrl+C` dừng từng tiến trình; dữ liệu SQLite vẫn được giữ. Đây là cách chạy local; repository chưa cung cấp service manager/container deployment.

## 5. Bật guild/channel và gửi message thử

Dùng DB local dành cho thử nghiệm và mock mode. Các ID `setup-*` bên dưới là dữ liệu tổng hợp, không phải Discord ID thật; không chạy smoke này trên DB production.

Nhập các key đã đặt trong `.env` mà không ghi giá trị vào lịch sử shell:

```bash
BASE_URL=http://127.0.0.1:8000
read -r -s -p 'Admin backend key: ' COCONERD_ADMIN_API_KEY; printf '\n'
read -r -s -p 'Bot backend key: ' COCONERD_BOT_API_KEY; printf '\n'
```

Bật guild/channel (HTTP 200). `PUT` thay toàn bộ allowlist của guild, nên dùng ID thử riêng:

```bash
curl --fail-with-body --silent --show-error -X PUT \
  "$BASE_URL/api/v1/admin/guilds/setup-guild/settings" \
  -H "X-Admin-API-Key: $COCONERD_ADMIN_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"enabled":true,"allowed_channel_ids":["setup-channel"],"retention_days":365}'
```

Tạo payload có timestamp hiện tại để tránh bị retention xóa nếu dùng ví dụ cũ:

```bash
python - <<'PY' > /tmp/coconerd-setup-message.json
from datetime import UTC, datetime
import json
print(json.dumps({
    'guild_id': 'setup-guild', 'channel_id': 'setup-channel',
    'message_id': 'setup-message-1', 'author_id': 'setup-user', 'author_name': 'Setup User',
    'content': 'Atlas: Lan phụ trách QA cho bản beta.',
    'created_at': datetime.now(UTC).isoformat(), 'reply_to_message_id': None,
}, ensure_ascii=False))
PY
curl --fail-with-body --silent --show-error -i \
  "$BASE_URL/api/v1/messages" \
  -H "X-API-Key: $COCONERD_BOT_API_KEY" \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/coconerd-setup-message.json
```

Mong đợi HTTP **202** và `{"message_id":"setup-message-1","status":"accepted"}`. Gửi lại cùng ID không tạo thêm message/job và không cập nhật nội dung cũ. Khi muốn thử message mới, đổi `message_id`.

Sau khi worker xử lý, claim action với bot giả lập:

```bash
curl --fail-with-body --silent --show-error \
  "$BASE_URL/api/v1/actions/claim" \
  -H "X-API-Key: $COCONERD_BOT_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"worker_id":"setup-bot-01","limit":1}'
```

`[]` nghĩa là chưa có action đủ điều kiện; chờ và thử lại với khoảng nghỉ. Action đầu tiên cho topic mới là `CREATE_THREAD`. Đây là claim thật trên DB thử và lease có hạn. Tiếp tục theo [claim/ACK](BOT_INTEGRATION.md#4-claim-thực-thi-và-ack), không ACK ID thread giả trong DB dùng cho Discord thật.

## 6. Kiểm tra và chẩn đoán

```bash
pytest -q tests/backend/test_architecture.py tests/backend/test_api_contract.py \
  tests/backend/test_bot_integration.py
ruff check backend tests scripts alembic
```

Các test dùng DB tạm và provider giả lập, không gọi Meta hoặc Discord. Xem [TESTING.md](TESTING.md) cho suite đầy đủ.

**Kiểm chứng hướng dẫn ngày 2026-11-04:** 12 test về kiến trúc/API contract/bot integration đã qua. Smoke trên thư mục tạm dùng `.env.example` với key giả đã chạy migration tới `20261104_0003`, `alembic check`, kiểm tra integrity/foreign keys, backup, hai CLI API/worker và các lệnh `curl` cấu hình/ingest/claim trong tài liệu. ACK tạo thread, ACK lặp và ACK summary đều thành công; queue sau đó rỗng. Chỉ dùng mock, không thay DB runtime hoặc gọi Meta/Discord. Chưa kiểm thử cài dependency trên một máy Linux mới hoàn toàn.

| Triệu chứng | Kiểm tra |
| --- | --- |
| `organizer-api: command not found` | Activate đúng venv và cài editable package trong checkout này |
| `unable to open database file` | Thư mục cha đã tồn tại, đúng URL và user có quyền ghi |
| `no such table` | Chạy migration, đối chiếu `alembic current` và DB URL của cả ba tiến trình |
| Health worker unavailable | Worker đang chạy, cùng DB và có heartbeat mới |
| `401` / `503` | Sai key/header / credential backend chưa đặt hoặc chỉ có khoảng trắng |
| `403` khi ingest | Guild bật và đúng channel ID trong allowlist |
| `202` nhưng chưa có action | Worker, trạng thái review, defer/irrelevant, pending dependency hoặc sync paused |
| `409` khi ACK | Đúng worker/token, lease chưa hết và kết quả khớp ACK trước đó |
| `429` | Tôn trọng `Retry-After`; ingest, claim và ACK cùng tiêu hao quota bot |
| Meta không chạy | Mock đã tắt, key/model hợp lệ; xem log worker và [review](MANUAL_REVIEW.md) |

Trước khi bot ở máy khác kết nối: đặt địa chỉ bind phù hợp, giới hạn mạng truy cập, dùng TLS qua reverse proxy và cấu hình bot bằng URL backend thực tế. `0.0.0.0` là địa chỉ bind, không phải URL client. Bot server không cần CORS; CORS dành cho request từ browser và không thay thế xác thực.
