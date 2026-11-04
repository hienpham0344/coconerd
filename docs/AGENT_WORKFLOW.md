# Agent workflow

HTTP ingestion gọi `application/services/messages.py` để lưu message/job qua Unit of Work. Worker gọi cùng lớp use case; SQL nằm trong repository. Xem [ranh giới kiến trúc](BACKEND_ARCHITECTURE.md).

```text
Discord bot gửi từng message gốc
  -> API lưu message + job trong một transaction -> 202 Accepted
  -> worker claim lease
  -> TopicTools đọc reply, tin gần đây, topic index và evidence
  -> local ranker chọn tối đa 5 topic cards
  -> local rule: irrelevant/defer, hoặc đặt chỗ một lượt gọi Meta
  -> Meta trả JSON Schema theo topic-policy-v3
  -> kiểm tra evidence IDs, shortlist, guild và trạng thái topic
  -> lưu association + decision + summary version + outbox trong một transaction
  -> bot claim action và ACK kết quả Discord

defer (missing_context/ambiguous)
  -> WAITING nếu còn hạn mức và chưa xét lại
  -> lời giải thích hợp lệ -> PENDING -> xét lại đúng một lần
  -> hết thời gian -> SUCCEEDED, quyết định vẫn defer, không gọi model
```

## Tools và retrieval

`TopicTools` gồm `get_reply_chain`, `search_topics`, `get_topic_evidence`. Đây là hàm đọc dữ liệu do code điều phối, không phải vòng function calling trả phí. Chúng không cho model tự viết SQL, sửa DB hoặc gọi Discord.

- Reply ancestry: tối đa 3 tin trước đó cùng guild/channel. Tin gần đây lấy trong 10 phút, ưu tiên từ khóa và tác giả; đây chỉ là cách chọn context.
- Search: chỉ mục `topic_search_terms` tìm trên các topic `ACTIVE`, `DORMANT`, `RESUMED` cùng guild, không có cutoff theo độ mới. Tối đa 30 kết quả search được hợp nhất với 30 topic gần đây; direct reply được ưu tiên trong giới hạn 60 ứng viên.
- Ranking: title có trọng số cao hơn description và summary. Chuẩn hóa dấu, alias và gợi ý viết tắt cục bộ chỉ phục vụ retrieval; tin gốc không bị sửa. Lời giải thích có thể hỗ trợ ranking, nhưng vẫn được gửi riêng khỏi target.
- Evidence: đọc tối đa 2 tin trước đó cùng channel gắn với ứng viên đầu tiên. Tổng context tối đa 6 tin, 400 ký tự mỗi tin, 1.600 ký tự tổng; ưu tiên lời giải thích, reply, evidence rồi recent.
- Prompt nhận tối đa 5 cards; title, description, overview và các danh sách được thu gọn. Hiện có thể đọc summary cho tối đa 60 ứng viên; chưa tối ưu gộp các truy vấn này.

Đây là retrieval từ khóa cục bộ. Chưa có embeddings, vector DB hay model subagent. Chỉ bổ sung retrieval ngữ nghĩa hoặc một model phụ khi evaluation cho thấy lợi ích vượt chi phí; không dùng số đo của nghiên cứu bên ngoài làm accuracy của ứng dụng.

## Policy và bằng chứng

`topic-policy-v3` định nghĩa topic theo vấn đề/dự án/mục tiêu, không chỉ từ khóa chung. Reply có thể đổi chủ đề; nhiều chủ đề trong một target cần `defer`. Câu thiếu tham chiếu không mặc nhiên là `irrelevant`.

Tin rỗng dùng `local-empty`; một số câu xác nhận hoặc viết tắt mơ hồ không có reply/lời giải thích dùng `local-defer`. Cả hai không khởi tạo provider, không cần Meta key và ghi nhận zero tokens. Gợi ý ngôn ngữ dùng từ điển có giới hạn, không phải một model sửa chính tả.

Meta nhận nội dung chat như dữ liệu không đáng tin, không phải system instructions. Schema gồm outcome, topic/title, confidence, reason, các nhóm memory, `evidence_message_ids`, `defer_reason`, `multiple_topics`. Server yêu cầu assignment chứa ID target và không chứa evidence ID chưa cung cấp; topic hiện có phải thuộc shortlist. Title trùng dẫn đến defer để tránh ép gộp. Trước ghi dữ liệu, server kiểm tra topic vẫn tồn tại và chưa đóng.

Quyết định bị từ chối hoặc deferred không tạo summary hay action. **Kiểm tra evidence IDs không kiểm chứng được tính đúng nghĩa của suy luận hoặc từng claim trong summary.** Model vẫn có thể chọn sai trong các evidence hợp lệ; confidence chưa được hiệu chỉnh.

## Chờ ngữ cảnh và ngân sách

Chỉ `defer` vì `missing_context` hoặc `ambiguous` mới chờ. Job chờ tối đa 10 phút từ lúc quyết định; tin làm rõ phải được tạo sau target và trong vòng 10 phút tính theo timestamp target. Tin phải ở cùng guild/channel, reply trực tiếp target, hoặc cùng tác giả với tiền tố như `ý mình là`, `mình nói`, `i mean`, `to clarify`. Reply vào tin khác không được dùng. Không có reply thì chỉ xét target đang chờ gần nhất của tác giả; có tin mới hơn của tác giả xen giữa, hoặc timestamp trùng gây mơ hồ, thì không tự đoán target cũ.

Khi vào WAITING, worker còn quét tối đa 30 tin có khả năng làm rõ đã đến trước quyết định, ưu tiên explicit reply. Duplicate ingestion không đánh thức lại job. Wakeup đổi trạng thái nguyên tử và tăng `reassessment_count` lên 1; lần xét lại không mở vòng chờ mới. Hết hạn được xử lý trong lần quét claim kế tiếp, giữ association `DEFERRED` và không tạo action.

Worker đặt chỗ lượt gọi bằng transaction riêng **trước** khi tạo provider/gọi Meta. `model_call_count` tối đa 2 trong suốt đời job; retry hoặc rollback không xóa bộ đếm. Đây là hạn mức lần thử, không phải hóa đơn: lỗi khởi tạo hoặc crash sau đặt chỗ có thể mất một lượt dù chưa gửi HTTP. SDK không retry nội bộ. Hết hạn mức hoặc output bị cắt kết thúc job ở `DEAD`; các lỗi khác vẫn chịu giới hạn retry và hai lượt này.

Chỉ association `DEFERRED` được tự thay sau xét lại; giữ cả lịch sử quyết định. Association đã gán hoặc `IRRELEVANT` không được tự ghi đè. Chưa có API sửa phân loại thủ công hay xây lại summary/outbox sau sửa.

## Memory và cache

Summary lưu theo version và source IDs. Có thay đổi overview/danh sách mới ghi version và `UPSERT_SUMMARY`; các quyết định trước được giữ. Chỉ mục được cập nhật cùng transaction với topic/summary và xóa theo topic/guild. Lời giải thích giúp hiểu target, nhưng prompt không cho gán các sự kiện mới của lời giải thích thành lời của target.

System prompt/schema ổn định đứng trước phần biến đổi; cache key có version policy/ngôn ngữ. Đây là prompt-prefix cache phía Meta, không tái dùng quyết định topic giữa các tin. Usage ghi input, output, cached, reasoning và latency nếu có; giá trị thiếu là unknown. Cached thuộc input, reasoning thuộc output, không cộng hai lần.

Sau thời gian inactive, worker đổi `ACTIVE` thành `DORMANT`, không tự đóng topic. Tin phù hợp có thể mở lại episode. `MockMetaProvider` chỉ kiểm thử luồng, không đo chất lượng Meta. Bot Discord và khả năng chạy tải đồng thời chưa được kiểm chứng bằng các kiểm tra này.
