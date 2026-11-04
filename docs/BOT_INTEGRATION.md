# Tích hợp Discord bot

Đối tượng: người viết bot bằng Discord SDK bất kỳ. Backend không giữ Discord token, không gọi Discord API và không cung cấp SDK client riêng. Trước tiên hoàn tất [setup backend/DB](BACKEND_SETUP.md); schema HTTP chuẩn nằm trong [API contract](API_CONTRACT.md) và `/openapi.json`.

## 1. Thông tin cần bàn giao

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
- Nội dung hiện là text. Backend chưa có attachment/OCR/audio extraction và chưa có giao thức edit/delete.

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

Bot cần hai luồng độc lập: nhận/gửi message và polling outbox. Trong pilot, có thể bắt đầu claim `limit=1`, poll mỗi 2 giây lúc rỗng và tăng backoff khi lỗi. Đây là giá trị gợi ý ở client; tính tổng ingest/claim/ACK theo tải để không vượt quota backend.

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
| `CREATE_THREAD` | Dùng `title`, xử lý bản sao nguồn từ `source_*` nếu có; tạo thread và lưu `topic_id → thread_id` |
| `APPEND_MESSAGE` | Dùng `source_*`, gửi bản sao có tác giả và link nguồn vào thread của topic |
| `UPSERT_SUMMARY` | Dùng `summary_id`, `version`, `summary`; tạo/sửa summary message do bot sở hữu, lưu message ID và version |
| `RENAME_THREAD` | Được enum cho phép nhưng luồng projection/recovery hiện chưa sinh type này; nếu gặp action chưa biết, báo lỗi để review thay vì ACK im lặng |

Claim không có trường top-level `discord_thread_id`. Bot đọc mapping của mình hoặc gọi `GET /api/v1/topics/{topic_id}?guild_id=...` để lấy thread đã được ACK. `payload.summary` có `overview`, `proposals`, `decisions`, `open_questions`, `action_items`; không phải chuỗi message Discord đã định dạng.

Bot chịu trách nhiệm chia nội dung theo giới hạn Discord, vô hiệu mention ngoài ý muốn, ghi tác giả và link `https://discord.com/channels/{guild_id}/{channel_id}/{source_message_id}`. Chỉ có source ID chưa chứng minh source còn tồn tại. Summary message ID chưa có endpoint riêng để lấy lại; bot cần lưu nó bền vững. Nếu một action tạo nhiều message, lưu toàn bộ receipt ở bot và thống nhất ID đại diện dùng cho ACK.

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
- [ ] Gửi một message → nhận 202 → worker → CREATE_THREAD → complete → summary.
- [ ] Reply cùng topic → APPEND_MESSAGE/summary; có mapping thread và summary message bền vững.
- [ ] Gửi lại cùng message ID không tạo job/thread mới.
- [ ] Output của bot không bị ingest lại.
- [ ] Mô phỏng mất ACK và restart bot; khôi phục receipt, không tạo trùng side effect.
- [ ] Lease hết hạn, token cũ bị từ chối; lỗi quyền/rate limit có backoff và đường review.
- [ ] Message dài, mentions và topic khác channel không làm lộ nội dung hoặc sai định dạng.

Repo đã có kiểm thử HTTP → SQLite migrate → worker → bot giả lập, nhưng chưa chứng minh checklist này trên Discord thật. Theo dõi độ tuổi queue, action DEAD, defer, latency và chất lượng summary trong pilot trước khi mở rộng server/tải.
