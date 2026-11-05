# Tích hợp Discord bot

Repo có sẵn consumer trong `bot/`: chạy `python -m pip install -r bot/requirements.txt`,
sau đó `python -m bot.main`. `/setup` cấu hình channel trực tiếp trong Discord;
`/summarize topic_id:0` liệt kê topic trong Input Channel. Consumer claim từng action,
gửi lại `lease_token` khi ACK và lưu mapping Thread bằng completion có lease.
Bot đăng một tin tiêu đề trong Output Channel đã chọn, tạo public Thread gắn vào
tin đó và chuyển nguyên văn tin thành viên vào Thread theo dạng `[tên]-tin nhắn`.
Tin tiêu đề có ghi chú tự cập nhật từ summary: nội dung chính, đề xuất, điều đã chốt,
việc cần làm và câu hỏi còn mở. Mỗi lần cập nhật sửa cùng tin đầu, không gửi thêm tin.
Worker chỉ đưa nội dung đáng ghi nhớ vào topic; chuyện phiếm không tạo Thread hay action.
Các câu hỏi thực tế về lịch học, họp hoặc ăn uống vẫn có thể tạo topic khi chưa chốt.
Ghi chú dài ưu tiên thông tin mới nhất. Policy áp dụng khi worker xử lý message;
không tự xóa hoặc phân loại lại conversation cũ.
Thành viên gọi `/summarize` ngay trong Thread để đăng thêm
tóm tắt tại đó; không cần nhập `topic_id`. Thread phải thuộc Output Channel đã
setup và có mapping topic trong cùng guild. Trong Input Channel, cú pháp chọn/
liệt kê topic bằng `topic_id` được giữ nguyên.
Receipt Discord lưu qua backend API vào bảng `delivery_receipts` của PostgreSQL,
chỉ chứa ID và khóa, không chứa nội dung tin. Bot không cần mật khẩu database.
Receipt được giữ qua restart và thay máy chạy bot. Khi mapping còn trỏ Thread ở kênh cũ,
action kế tiếp tạo Thread ở Output Channel hiện tại, sao chép lịch sử topic theo
thứ tự thời gian rồi cập nhật mapping bằng ACK có lease. Tin/Thread cũ được giữ lại.
Các kiểm thử tự động dùng Discord mocks; vẫn cần kiểm thử quyền và delivery trên guild pilot.

Đối tượng: người viết bot bằng Discord SDK bất kỳ. Backend không giữ Discord token, không gọi Discord API và không cung cấp SDK client riêng. Trước tiên hoàn tất [setup backend/DB](BACKEND_SETUP.md); schema HTTP chuẩn nằm trong [API contract](API_CONTRACT.md) và `/openapi.json`.

## 1. Thông tin cần bàn giao

Phản hồi khi tag bot và worker phân loại/tóm tắt đều dùng Meta Model API.
Đặt `COCONERD_MODEL_API_KEY` trong `.env`; endpoint là `https://api.meta.ai/v1`,
model mặc định `muse-spark-1.3`. Bot dùng cùng `COCONERD_META_MODEL_NAME`,
`COCONERD_LLM_REASONING_EFFORT` (mặc định `low`) và `COCONERD_LLM_MAX_TOKENS`
(mặc định 2048) với worker. Package `openai` là SDK truyền request tới Meta.
`COCONERD_MOCK_LLM=true` chỉ dành cho worker offline; chat vẫn cần key Meta.
Chat timeout sau 15 giây, không tự retry; khi lỗi dùng câu meme tĩnh có sẵn.
Không có AI provider dự phòng. Restart bot và worker sau khi đổi cấu hình.

`COCONERD_AGENT_MODE=task` chọn profile `chat` cho mention; cấu hình riêng qua
`COCONERD_TASK_PROFILES`. Profile có thể giảm deadline hoặc đổi token/effort/model
Meta mà không tác động task worker. Xem [điều phối task](TASK_ORCHESTRATION.md).

| Thông tin | Nơi sử dụng |
| --- | --- |
| URL backend, ví dụ `http://127.0.0.1:8000` khi cùng máy | HTTP client trong bot |
| `COCONERD_BOT_API_KEY` | Header `X-API-Key` của bot |
| `COCONERD_ADMIN_API_KEY` | Tool/admin cấu hình và review; tách khỏi consumer thông thường |
| Guild ID và channel ID thật được phép ingest | Admin allowlist và bộ lọc sự kiện bot |
| `worker_id` duy nhất cho mỗi tiến trình consumer | Claim và ACK; ví dụ `discord-consumer-01` |
| `COCONERD_ACTION_LEASE_SECONDS`, mặc định 60 | Giới hạn thời gian claim → thực thi → ACK |
| Discord token | Chỉ ở ứng dụng bot; không gửi vào backend |

Bot chỉ cần HTTP; không mở file `data/coconerd.db` và không import repository Python. Không đưa bot/admin key vào JavaScript chạy trên browser.

Bot key hiện dùng chung toàn backend; `worker_id` không giới hạn guild. Claim chưa có bộ lọc guild/channel và có thể giao action của bất kỳ guild đang có trong DB. Nếu các bot/consumer phục vụ tập guild khác nhau, cần dispatcher chung có thể định tuyến đúng hoặc backend/DB tách biệt; không chỉ đổi `worker_id` rồi giả định action đã được chia theo guild. Bot key cũng không phải credential phân quyền riêng cho từng guild.

## 2. Quyền và sự kiện Discord

Với pilot đọc hội thoại guild, cấu hình Gateway intents phù hợp trong SDK, gồm `GUILDS`, `GUILD_MESSAGES` và quyền đọc nội dung `MESSAGE_CONTENT`. Bật Message Content Intent trong Developer Portal và đáp ứng điều kiện xét duyệt nếu ứng dụng thuộc diện yêu cầu; thiếu intent có thể khiến `content` rỗng. Xem [Discord Gateway / Message Content Intent](https://docs.discord.com/developers/events/gateway#message-content-intent).

Kiểm tra quyền tại channel nguồn và thread đích trước khi pilot: xem channel, đọc lịch sử khi cần tải message cũ, gửi message và tạo public thread. Quyền `SEND_MESSAGES` không thay thế `SEND_MESSAGES_IN_THREADS`. Private thread/locked thread cần chính sách truy cập riêng. Xem [Discord Threads / Permissions](https://docs.discord.com/developers/topics/threads#permissions).

Admin bật đúng guild/channel qua `PUT /api/v1/admin/guilds/{guild_id}/settings`. Allowlist backend kiểm soát ingest; nó không phải bản sao Discord ACL. Retrieval hiện cùng guild và có thể chọn topic ở channel khác: bot phải kiểm tra quyền/phạm vi người xem trước khi sao chép nội dung vào thread đích, không chỉ kiểm tra quyền của bot.

## 3. Nhận message và gửi backend

- Chỉ gửi guild/channel đã thống nhất; backend không hỗ trợ DM.
- Bỏ qua message do chính bot tạo và output đã mirror vào thread để tránh vòng lặp. Quyết định rõ có nhận message của bot/webhook khác hay không.
- Gửi từng message gốc; không gộp nhiều người/chủ đề thành một `content`.
- Giữ ID dưới dạng **string** xuyên suốt để tránh làm tròn số lớn khi dùng JavaScript.
- `created_at` dùng thời gian message gốc có timezone; `reply_to_message_id` là ID message được reply hoặc `null`.
- Giữ nguyên `content` và URL thành viên gửi; `attachments` lưu metadata file Discord (ID, filename, URL, content_type, size, spoiler). Tin chỉ có ảnh/file vẫn được nhận dù `content` rỗng. Bot không mở link, OCR hoặc phân tích nội dung ảnh/audio bằng AI; chưa có giao thức edit/delete.

Bot sao chép lại ảnh/file vào Thread qua Discord SDK, giữ tên và spoiler, với receipt riêng cho từng attachment để retry/backfill không gửi lại file đã ghi nhận. Chỉ tải attachment lấy từ message nguồn trong cùng guild; metadata URL không được dùng để tải tùy ý. File quá giới hạn dung lượng guild hoặc nguồn đã mất sẽ được giữ bằng tên/link kèm lý do rõ ràng. Bot cần quyền đọc lịch sử Input Channel và `Attach Files` tại Thread để tải lại file; thiếu quyền upload thì gửi link dự phòng. Link trong tin text được giữ nguyên, URL bình thường không bị cắt giữa hai phần tin.

Tin chỉ có file reply vào message đã thuộc topic sẽ vào cùng topic; nếu không có điểm neo hợp lệ thì tạo topic đính kèm riêng với tên trung tính. Không suy diễn nội dung ảnh hoặc tạo fact từ ảnh. Khi cài bản này cho DB cũ, chạy `alembic upgrade head` (migration `20261105_0006`) trước khi restart API, worker và bot. Migration chỉ thêm cột JSON metadata; không sao chép dữ liệu ảnh vào DB.

Mapping sự kiện Discord → JSON:

```json
{
  "guild_id": "123456789012345678",
  "channel_id": "234567890123456789",
  "message_id": "345678901234567890",
  "author_id": "456789012345678901",
  "author_name": "Lan",
  "content": "Atlas: Lan phụ trách QA cho bản beta.",
  "created_at": "2026-11-04T09:00:00+07:00",
  "reply_to_message_id": null
}
```

`POST /api/v1/messages` với `X-API-Key`, `Content-Type: application/json`. `202` nghĩa là backend đã lưu message/job, chưa có nghĩa AI đã gán topic. Timeout/mất kết nối: giữ request trong hàng đợi bền vững của bot và thử lại cùng `(guild_id, message_id)`. Gửi lại ID cũ không cập nhật snapshot hoặc kích hoạt phân loại mới.

`defer`/`irrelevant` không tạo action. Muốn chẩn đoán một message, admin dùng `GET /api/v1/guilds/{guild_id}/messages/{message_id}/review`; chưa có endpoint job-status dành riêng cho bot.

## 4. Claim, thực thi và ACK

Bot có hai luồng độc lập: nhận/gửi message và xử lý outbox. Consumer hiện mở WebSocket `/api/v1/actions/events` bằng header `X-API-Key`; nhận `{"type":"actions_available"}` thì claim ngay bằng HTTP với `limit=1`. Khi vẫn có action, bot xử lý tiếp ngay, không nghỉ giữa các action. Socket tự reconnect với backoff 1–30 giây; heartbeat ứng dụng mỗi 20 giây. Khi không có tín hiệu, bot vẫn poll dự phòng mỗi 2,5 giây để phục hồi retry/lease hết hạn hoặc tín hiệu bị lỡ. Tổng ingest/claim/ACK vẫn tính quota backend.

PostgreSQL dùng `LISTEN/NOTIFY` để đánh thức worker khi job mới commit và báo API khi action mới commit. Mỗi worker/API process giữ một kết nối listener trong pool, tự kết nối lại và quét backlog. Tín hiệu không chứa nội dung chat; dữ liệu, lease và receipt vẫn lấy từ HTTP/DB. SQLite trong test chỉ dùng polling dự phòng. Không cần Redis, dependency mới hoặc migration mới cho socket. Để bật thay đổi trên runtime, restart cả API, worker và bot bằng các lệnh hiện có; reverse proxy phải cho phép WebSocket Upgrade tại `/api/v1/actions/events`. URL `https://` của backend tự chuyển thành `wss://`, dùng nguyên đường dẫn prefix nếu có.

```http
POST /api/v1/actions/claim
X-API-Key: <bot-backend-key>
Content-Type: application/json

{"worker_id":"discord-consumer-01","limit":1}
```

Response là **mảng**, rỗng khi chưa có action đủ điều kiện:

```json
[
  {
    "action_id": "action-001",
    "type": "CREATE_THREAD",
    "topic_id": "topic-001",
    "guild_id": "123456789012345678",
    "channel_id": "234567890123456789",
    "payload": {
      "title": "Atlas beta",
      "source_message_id": "345678901234567890",
      "source_author_name": "Lan",
      "source_created_at": "2026-11-04T09:00:00+07:00",
      "source_content": "Atlas: Lan phụ trách QA cho bản beta."
    },
    "status": "CLAIMED",
    "lease_token": "00000000-0000-4000-8000-000000000001"
  }
]
```

Chu trình consumer cần triển khai:

```text
claim → kiểm tra action_id trong kho kết quả bot
      → nếu chưa thực hiện: gọi Discord, lưu receipt bền vững
      → nếu đã thực hiện: dùng receipt đã lưu
      → complete bằng worker_id + lease_token của claim hiện tại
```

### Ánh xạ action

| Type | Payload và hành động bot |
| --- | --- |
| `CREATE_THREAD` | Đăng `title` kèm ghi chú từ `payload.summary` vào Output Channel, tạo Thread từ tin đầu, sao chép nguồn/lịch sử và lưu `topic_id → thread_id` |
| `APPEND_MESSAGE` | Dùng `source_*`, gửi `[tên]-tin nhắn` vào Thread của topic |
| `UPSERT_SUMMARY` | Sửa ghi chú trên tin đầu của Thread theo `payload.summary`; receipt theo phiên bản tránh sửa lại khi retry hoặc ghi đè bởi bản cũ |
| `RENAME_THREAD` | Được enum cho phép nhưng luồng projection/recovery hiện chưa sinh type này; nếu gặp action chưa biết, báo lỗi để review thay vì ACK im lặng |

Claim không có trường top-level `discord_thread_id`. Bot đọc mapping của mình hoặc gọi `GET /api/v1/topics/{topic_id}?guild_id=...` để lấy thread đã được ACK. `payload.summary` có `overview`, `proposals`, `decisions`, `open_questions`, `action_items`; không phải chuỗi message Discord đã định dạng.

Bot chia nội dung dài theo giới hạn Discord, giữ tên và nội dung gốc, vô hiệu mention
ngoài ý muốn. Source ID là khóa receipt để tránh sao chép lại cùng tin; receipt lưu
riêng từng phần khi một tin dài cần nhiều message. Ghi chú dùng ID tin đầu đã lưu
trong receipt và phiên bản đã cập nhật. ACK tin nguồn dùng ID của phần đầu làm ID đại diện.

Sau khi Discord thực hiện thành công, ACK bằng dữ liệu thực:

```http
POST /api/v1/actions/action-001/complete
X-API-Key: <bot-backend-key>
Content-Type: application/json

{
  "worker_id": "discord-consumer-01",
  "lease_token": "00000000-0000-4000-8000-000000000001",
  "discord_thread_id": "567890123456789012",
  "discord_message_id": null
}
```

Response: `{"action_id":"action-001","status":"SUCCEEDED"}`. `CREATE_THREAD` bắt buộc có `discord_thread_id`; message action nên gửi ID message Discord đã ghi. ACK lặp với cùng kết quả an toàn; kết quả khác trả `409`.

Khi chuyển Thread sang Output Channel hoặc thay Thread đã bị xóa, completion thêm
`previous_discord_thread_id` (nullable) và `discord_channel_id`. Backend chỉ thay
mapping nếu mapping cũ còn khớp, destination đúng Output Channel hiện tại và lease
còn hợp lệ; không khớp trả `409` và không hoàn tất action.

### Lease và thứ tự

- Mọi `/complete` và `/fail` dùng cùng `worker_id` và đúng `lease_token` từ lần claim hiện tại.
- Lease mặc định 60 giây; không có API gia hạn. Chỉ claim lượng việc xử lý kịp, kể cả thời gian chờ rate limit và retry ACK. Response chưa có deadline riêng, nên client cần biết cấu hình lease.
- Hết lease và bị reclaim sẽ tạo token mới; ACK cũ bị từ chối. Dùng lại `worker_id` không làm token cũ hợp lệ.
- Backend tuần tự hóa action cùng topic, gồm thời gian backoff; topic khác có thể xử lý đồng thời. Dependency tạo thread phải thành công trước action phụ thuộc.
- Khi mất ACK sau side effect, bot không được tạo lại thread/message một cách mù quáng. Dùng receipt hoặc đối chiếu Discord; một bảng idempotency riêng không tự loại hết cửa sổ crash giữa Discord request và lưu receipt.

## 5. Retry, lỗi và phục hồi

Nếu thao tác Discord thất bại và chưa có side effect thành công, báo lỗi có phân loại:

```http
POST /api/v1/actions/action-001/fail
X-API-Key: <bot-backend-key>
Content-Type: application/json

{
  "worker_id": "discord-consumer-01",
  "lease_token": "00000000-0000-4000-8000-000000000001",
  "error_type": "DiscordUnavailable",
  "error_message": "Temporary Discord failure; no operation completed",
  "retryable": true
}
```

`retryable=true` đưa action về `PENDING` nếu còn attempts; backend áp dụng backoff. Lỗi quyền/xóa thread hoặc action không hỗ trợ cần xử lý rõ và có thể kết thúc `DEAD`, rồi admin recovery. Không gửi token, header hoặc raw exception chứa credential trong `error_message`.

| Tình huống | Hành vi client |
| --- | --- |
| Backend timeout/5xx khi ingest | Retry cùng message ID, có backoff |
| Backend `429` | Đợi `Retry-After`; claim và complete/fail cũng tính quota |
| Backend `401` / `503` | Kiểm tra key/header hoặc cấu hình; không retry nóng |
| Backend `403` | Kiểm tra guild/channel allowlist |
| Backend `409` khi ACK | Dừng dùng lease cũ, giữ receipt và đối chiếu/reclaim hoặc admin recovery |
| Backend `422` | Sửa body/timestamp/thread ID; không retry nguyên request sai |
| Discord `429` | Dùng xử lý rate limit của SDK/header; bảo đảm không vượt lease khi chờ |
| Discord timeout, chưa rõ side effect | Đối chiếu receipt/Discord trước khi thực hiện lại |

Không hardcode quota Discord; tham khảo [Discord Rate Limits](https://docs.discord.com/developers/topics/rate-limits). Quota backend hiện là 120 request/phút/bot key, được chia sẻ cho các route bot có rate limit. Bắt đầu với batch nhỏ và điều chỉnh theo số request thực.

Manual correction có thể đánh dấu action cũ superseded và pause sync; bot phải tôn trọng việc không còn claim được action đó. Khi cần đối chiếu/khôi phục, dùng [MANUAL_REVIEW.md](MANUAL_REVIEW.md), không tự sửa SQL hoặc ACK giả để mở dependency.

## 6. Checklist pilot với bot thật

- [ ] DB ở head; API/worker cùng DB; health body báo `ok`.
- [ ] Backend bot key và Discord token khác nhau, không nằm trong client browser/log.
- [ ] Guild/channel thật đã allowlist; intent, permission và phạm vi người xem thread phù hợp.
- [ ] Gửi nội dung thực tế → nhận 202 → worker → CREATE_THREAD → complete; tin đầu có ghi chú, Thread có tin gốc.
- [ ] Reply bổ sung thông tin → APPEND_MESSAGE và cập nhật ghi chú cùng tin đầu; `/summarize` vẫn hoạt động trong Thread.
- [ ] Chuyện phiếm không tạo topic/action; đề xuất chưa chốt được ghi đúng trạng thái, không biến thành quyết định.
- [ ] Gửi lại cùng message ID không tạo job/thread mới.
- [ ] Output của bot không bị ingest lại.
- [ ] Mô phỏng mất ACK và restart bot; khôi phục receipt, không tạo trùng side effect.
- [ ] Lease hết hạn, token cũ bị từ chối; lỗi quyền/rate limit có backoff và đường review.
- [ ] Message dài, mentions và topic khác channel không làm lộ nội dung hoặc sai định dạng.

Repo đã có kiểm thử HTTP → SQLite migrate → worker → bot giả lập, nhưng chưa chứng minh checklist này trên Discord thật. Theo dõi độ tuổi queue, action DEAD, defer, latency và chất lượng summary trong pilot trước khi mở rộng server/tải.
