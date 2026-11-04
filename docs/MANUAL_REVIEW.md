# Sửa topic và khôi phục đồng bộ Discord

Các API dưới đây cần `X-Admin-API-Key`; không gửi admin key cho người dùng Discord. `actor` là nhãn do người giữ admin key khai báo, chưa phải danh tính Discord được server xác minh. Server không gọi Meta hoặc Discord trong thao tác review.

## Sửa một message bị gán nhầm

Ví dụ: message `discord-m` nói về Beta nhưng bị gán vào Atlas. Bot/admin client cần đọc:

1. `GET /api/v1/guilds/g/messages/discord-m/review` để lấy `revision`, topic hiện tại và lỗi/job/call budget.
2. `GET /api/v1/guilds/g/topics/old/sync` và tương tự cho `new` để lấy version cùng lịch sử action. Các endpoint đọc message/summary thông thường cung cấp nội dung để rà soát.
3. Chuẩn bị **toàn bộ snapshot memory mới** cho từng topic bị ảnh hưởng. Không gửi delta; dữ kiện bị bỏ khỏi snapshot sẽ không còn trong memory hiện tại, nhưng bản summary cũ vẫn được giữ.

`POST /api/v1/guilds/g/messages/discord-m/corrections`:

```json
{
  "request_id": "fix-beta-001",
  "actor": "moderator-name",
  "reason": "Tin nói về Beta, không phải Atlas",
  "expected_revision": 1,
  "target_topic_id": "new",
  "summaries": [
    {
      "topic_id": "old",
      "expected_version": 3,
      "overview": "Lan phụ trách QA cho Atlas",
      "decisions": [],
      "source_message_ids": ["atlas-qa-message"]
    },
    {
      "topic_id": "new",
      "expected_version": 2,
      "overview": "Beta phát hành thứ Sáu",
      "decisions": ["Phát hành thứ Sáu"],
      "source_message_ids": ["discord-m"]
    }
  ]
}
```

Các ID/version trên chỉ là ví dụ; lấy giá trị thực từ API. `proposals`, `decisions`, `open_questions`, `action_items` bỏ trống sẽ thành danh sách rỗng. Snapshot phải bao gồm cả dữ kiện cũ còn đúng. Nguồn phải là Discord message ID đang thuộc đúng topic **sau khi sửa**. Memory có nội dung phải có nguồn; server không tự kiểm chứng nội dung admin viết có đúng nghĩa hay không.

Response chứa revision mới, topic mới, `sync_paused_topic_ids`, các action đã hủy và `reconciliation_required`. Transaction đồng thời:

- Giữ message gốc, đổi association thành `MANUAL` và ghi decision/audit mới.
- Kết thúc job của message nhưng giữ nguyên số lượt model đã sử dụng.
- Tăng version các topic, ghi summary version mới và cập nhật chỉ mục.
- Hủy action PENDING; giữ action SUCCEEDED và lỗi DEAD đã xảy ra để đối chiếu. Action lỗi cũ được đánh dấu `superseded`, không được replay.
- Tạm dừng đồng bộ các topic liên quan. Worker vẫn xử lý message và cập nhật DB/memory của chúng, nhưng không tạo action mới; claim API cũng không phát action của topic đang dừng.

`target_topic_id=null` nghĩa là để message chưa gán theo quyết định thủ công; không tự gọi lại AI. API này chỉ gán vào topic có sẵn, chưa tạo/merge/split topic thủ công. Nếu chưa có association, dùng `expected_revision=0`. Topic đích đã đóng bị từ chối.

Nếu job đang xử lý hoặc còn action CLAIMED, server trả 409 và rollback toàn bộ. Hoàn tất action hợp lệ hoặc dùng quy trình recovery cho lease hết hạn rồi thử lại. Không sửa thẳng SQL để bỏ qua điều kiện này.

## Đối chiếu Discord rồi mở lại đồng bộ

Đọc `/topics/{topic_id}/sync?limit=50&offset=0` để xem trạng thái/version và action history (phân trang tối đa 100). Dùng message/summary hiện tại của topic để đối chiếu cả những message đến trong thời gian pause. Bot/operator phải tự sửa bản sao message, summary và thread trên Discord; backend không tự xóa hoặc gửi lại các side effect cũ.

Sau khi Discord đã phản ánh đúng dữ liệu của version hiện tại:

```json
{
  "request_id": "resume-beta-001",
  "actor": "moderator-name",
  "reason": "Đã đối chiếu message và summary trong thread Beta",
  "expected_version": 3,
  "discord_reconciled": true,
  "discord_thread_id": "verified-discord-thread-id"
}
```

Gửi đến `POST /api/v1/guilds/g/topics/new/resume-sync`. Có message mới làm đổi version trong lúc đối chiếu thì nhận 409: đọc lại và đối chiếu phần mới. Thao tác chỉ mở lại **action tương lai**, không replay lịch sử. Backend tin vào xác nhận của admin; chưa có kết nối Discord để tự xác minh thread/nội dung/quyền truy cập.

## Khôi phục action lỗi

`POST /api/v1/guilds/g/actions/{action_id}/recover`:

```json
{
  "request_id": "recover-create-001",
  "actor": "moderator-name",
  "reason": "Đã kiểm tra Discord, thread chưa được tạo",
  "expected_attempt_count": 5,
  "resolution": "not_performed"
}
```

`not_performed` chỉ dùng khi đã xác minh side effect chưa xảy ra: cấp thêm tối đa một lượt, không xóa attempt counter. Nếu đã thực hiện, dùng `resolution=performed` với `discord_thread_id` cho CREATE_THREAD, `discord_message_id` cho APPEND_MESSAGE/UPSERT_SUMMARY để ghi nhận kết quả mà không thực hiện lần nữa. Các action con DEAD vì `DependencyFailed` được mở lại khi khôi phục action cha; vẫn phải chờ cha SUCCEEDED trước khi claim.

Chỉ DEAD hoặc CLAIMED đã hết lease mới được recover. Live lease, sai attempt count, topic paused, action CANCELLED/superseded đều trả 409. Xác nhận sai `not_performed` có thể tạo trùng trên Discord; hệ thống không thể kiểm chứng thay người quản trị.

## Retry và lease phía bot

Mỗi lô `POST /api/v1/actions/claim` trả `lease_token` cùng từng action. Bot phải lưu `action_id`, `worker_id`, `lease_token`, dùng `action_id` để chống lặp side effect và gửi lại đúng token vào `/complete` hoặc `/fail`:

```json
{
  "worker_id": "bot-worker",
  "lease_token": "token-from-claim-response",
  "discord_thread_id": "created-thread-id"
}
```

Token cũ/thiếu token hoặc lease đã hết trả 409, kể cả bot dùng lại cùng worker_id. Đây là thay đổi tích hợp cần áp dụng cho bot khi nâng backend; record lease cũ chưa có token vẫn được xử lý đến lần claim tiếp theo. ACK thành công lặp cùng kết quả vẫn idempotent. Fencing trong DB không thay thế chống gửi trùng ở Discord khi mạng lỗi giữa thực hiện và ACK.

Mọi write review dùng `request_id` duy nhất trong guild. Retry cùng endpoint/resource/body trả receipt cũ; đổi body nhưng giữ ID trả 409. Request đồng thời có thể nhận conflict và cần retry/reload. Review hiện là API, chưa có giao diện hoặc Discord moderator command.
