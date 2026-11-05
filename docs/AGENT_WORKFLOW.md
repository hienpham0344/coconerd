# Agent workflow

HTTP ingestion gọi `application/services/messages.py` để lưu message/job qua Unit of Work. Worker gọi cùng lớp use case; SQL nằm trong repository. Xem [ranh giới kiến trúc](BACKEND_ARCHITECTURE.md).

```text
Discord bot gửi từng message gốc
  -> API lưu message + job trong một transaction -> 202 Accepted
  -> worker claim lease
  -> TopicTools đọc reply, tin gần đây, topic index và evidence
  -> local ranker chọn tối đa 5 topic cards
  -> local rule: irrelevant/defer, hoặc đặt chỗ một lượt gọi Meta
  -> TaskRouter chọn profile topic_classification/topic_memory từ facts trong shortlist
  -> Meta trả JSON Schema theo topic-policy-v6
  -> kiểm tra evidence IDs, shortlist, guild và trạng thái topic
  -> lưu association + decision + summary version + outbox trong một transaction
  -> bot claim action và ACK kết quả Discord

defer (missing_context/ambiguous)
  -> WAITING nếu còn hạn mức và chưa xét lại
  -> lời giải thích hợp lệ -> PENDING -> xét lại đúng một lần
  -> hết thời gian -> SUCCEEDED, quyết định vẫn defer, không gọi model
```

## Tools và retrieval

Luồng mention dùng task `chat`; worker dùng `topic_classification` hoặc `topic_memory`.
Router và execution guard dùng chung, mỗi invocation có deadline/input/output limits
và trace; phân loại và memory vẫn nằm trong một response. Chi tiết cấu hình và
giới hạn ở [điều phối task Meta](TASK_ORCHESTRATION.md).

`TopicTools` gồm `get_reply_chain`, `search_topics`, `get_topic_evidence`. Đây là hàm đọc dữ liệu do code điều phối, không phải vòng function calling trả phí. Chúng không cho model tự viết SQL, sửa DB hoặc gọi Discord.

- Reply ancestry: tối đa 3 tin trước đó cùng guild/channel. Tin gần đây lấy trong 10 phút. Khi không có reply, giữ tin gần nhất trước khi xếp các tin còn lại theo từ khóa và tác giả.
- Tiếp nối hội thoại: topic còn mở của tin trước đó trong cùng channel, cách tối đa 2 phút, được giữ trong shortlist với `conversation_predecessor_target`; tin nguồn có relation `conversation_predecessor`. Đây là bằng chứng để model xét ngữ nghĩa, không tự gán topic vì hai tin ở gần nhau. Explicit reply vẫn được ưu tiên.
- Search: chỉ mục `topic_search_terms` tìm trên các topic `ACTIVE`, `DORMANT`, `RESUMED` cùng guild, không có cutoff theo độ mới. Tối đa 30 kết quả search được hợp nhất với 30 topic gần đây; direct reply được ưu tiên trong giới hạn 60 ứng viên.
- Ranking: title có trọng số cao hơn description và summary. Chuẩn hóa dấu, alias và gợi ý viết tắt cục bộ chỉ phục vụ retrieval; tin gốc không bị sửa. Lời giải thích có thể hỗ trợ ranking, nhưng vẫn được gửi riêng khỏi target.
- Evidence: đọc tối đa 2 tin trước đó cùng channel gắn với ứng viên đầu tiên. Tổng context tối đa 6 tin, 400 ký tự mỗi tin, 1.600 ký tự tổng; ưu tiên lời giải thích/follow-up, reply, tin tiếp nối, evidence rồi recent.
- Prompt nhận tối đa 5 cards; title, description, overview và các danh sách được thu gọn. Summary của tối đa 60 ứng viên được đọc bằng một truy vấn batch theo guild. Card dùng 400 ký tự cuối overview và 3 item mới nhất mỗi danh sách. Chỉ mục ưu tiên phần memory gần đây; phrase alias có giới hạn hỗ trợ `sign in`/`đăng nhập`, `persistent storage engine`/`cơ sở dữ liệu`.

Đây là retrieval từ khóa cục bộ. Chưa có embeddings, vector DB hay model subagent. Chỉ bổ sung retrieval ngữ nghĩa hoặc một model phụ khi evaluation cho thấy lợi ích vượt chi phí; không dùng số đo của nghiên cứu bên ngoài làm accuracy của ứng dụng.

## Policy và bằng chứng

`topic-policy-v6` định nghĩa topic theo vấn đề/dự án/mục tiêu, không chỉ từ khóa chung. Họp hackathon, chia role backend/frontend/PM và chốt giờ họp của cùng team là một topic; các khía cạnh này không bị coi là nhiều chủ đề độc lập. Kế hoạch ăn uống hoặc dự án của team khác vẫn có thể là topic mới. Reply có thể đổi chủ đề; nhiều mục tiêu độc lập trong một target cần `defer`. Câu thiếu tham chiếu không mặc nhiên là `irrelevant`.

Tin rỗng dùng `local-empty`; một số câu xác nhận hoặc viết tắt mơ hồ không có reply/lời giải thích dùng `local-defer`. Cả hai không khởi tạo provider, không cần Meta key và ghi nhận zero tokens. Gợi ý ngôn ngữ dùng từ điển có giới hạn, không phải một model sửa chính tả.

Meta nhận nội dung chat như dữ liệu không đáng tin, không phải system instructions. Schema gồm outcome, topic/title, confidence, reason, các nhóm memory, `evidence_message_ids`, `defer_reason`, `multiple_topics`. Server yêu cầu assignment chứa ID target và không chứa evidence ID chưa cung cấp; topic hiện có phải thuộc shortlist. Title trùng dẫn đến defer để tránh ép gộp. Trước ghi dữ liệu, server kiểm tra topic vẫn tồn tại và chưa đóng.

Quyết định bị từ chối hoặc deferred không tạo summary hay action. **Kiểm tra evidence IDs không kiểm chứng được tính đúng nghĩa của suy luận hoặc từng claim trong summary.** Model vẫn có thể chọn sai trong các evidence hợp lệ; confidence chưa được hiệu chỉnh. Assignment dưới 0.7 chuyển thành `defer/ambiguous`; ngưỡng này là quy tắc bảo thủ, không có nghĩa confidence 0.7 là đúng 70%.

## Chờ ngữ cảnh và ngân sách

Chỉ `defer` vì `missing_context` hoặc `ambiguous` mới chờ. Job chờ tối đa 10 phút từ lúc quyết định; tin làm rõ phải được tạo sau target và trong vòng 10 phút tính theo timestamp target. Tin phải ở cùng guild/channel, reply trực tiếp target, hoặc cùng tác giả với tiền tố như `ý mình là`, `mình nói`, `i mean`, `to clarify`. Reply vào tin khác không được dùng. Không có reply thì chỉ xét target đang chờ gần nhất của tác giả; có tin mới hơn của tác giả xen giữa, hoặc timestamp trùng gây mơ hồ, thì không tự đoán target cũ.

Khi vào WAITING, worker còn quét tối đa 30 tin có khả năng làm rõ đã đến trước quyết định, ưu tiên explicit reply. Duplicate ingestion không đánh thức lại job. Wakeup đổi trạng thái nguyên tử và tăng `reassessment_count` lên 1; lần xét lại không mở vòng chờ mới. Hết hạn được xử lý trong lần quét claim kế tiếp, giữ association `DEFERRED` và không tạo action.

Hội thoại tự nhiên cũng có thể bổ sung bằng chứng: khi một tin tiếp nối trong cùng guild/channel được gán vào topic còn mở, worker đánh thức tối đa 6 tin đang chờ trong 2 phút trước đó. Không cần cùng tác giả hoặc reply trực tiếp; tin lặp nguyên nội dung và reply vào tin khác không kích hoạt luồng này. Ngữ cảnh được đánh dấu `conversation_followup`, kèm topic của tin tiếp nối trong shortlist. Model phải xét lại quan hệ ngữ nghĩa, có thể tiếp tục defer; hệ thống không tự gán topic chỉ vì hai tin ở gần nhau. Ví dụ, “hungry” có thể được xét lại khi có câu hỏi chọn món đã được gán topic. Giới hạn một lần xét lại và hai lượt gọi model vẫn áp dụng. Job đã kết thúc không tự được mở lại; bản sửa không replay lịch sử lên Discord.

Worker đặt chỗ lượt gọi bằng transaction riêng **trước** khi tạo provider/gọi Meta. `model_call_count` tối đa 2 trong suốt đời job; retry hoặc rollback không xóa bộ đếm. Đây là hạn mức lần thử, không phải hóa đơn: lỗi khởi tạo hoặc crash sau đặt chỗ có thể mất một lượt dù chưa gửi HTTP. SDK không retry nội bộ. Hết hạn mức hoặc output bị cắt kết thúc job ở `DEAD`; các lỗi khác vẫn chịu giới hạn retry và hai lượt này.

Chỉ association `DEFERRED` được tự thay sau xét lại; giữ cả lịch sử quyết định. Association đã gán hoặc `IRRELEVANT` không được tự ghi đè. Admin có API sửa phân loại với revision, bản memory đã rà soát và audit; sửa thủ công không mở lại ngân sách model. Xem [luồng review](MANUAL_REVIEW.md).

## Memory và cache

Summary lưu theo version và source IDs. Có thay đổi overview/danh sách mới ghi version và `UPSERT_SUMMARY`; các quyết định trước được giữ. Chỉ mục được cập nhật cùng transaction với topic/summary và xóa theo topic/guild. Lời giải thích giúp hiểu target, nhưng prompt không cho gán các sự kiện mới của lời giải thích thành lời của target.

Overview được tích lũy theo facts thay vì bị ghi đè toàn bộ. `memory_replacements` cho phép thay/xóa một fact cũ khi model chỉ ra đúng field, nguyên văn fact cũ và một quote nguyên văn trong target. Validator kiểm tra card đã cung cấp rồi kiểm tra lại memory đầy đủ trước khi ghi: tham chiếu cắt ngắn/stale bị defer. Việc quote tồn tại không chứng minh diễn giải đúng; mâu thuẫn mà model không nhận ra vẫn có thể tồn tại.

System prompt/schema ổn định đứng trước phần biến đổi; cache key có version policy/ngôn ngữ. Đây là prompt-prefix cache phía Meta, không tái dùng quyết định topic giữa các tin. Usage ghi input, output, cached, reasoning và latency nếu có; giá trị thiếu là unknown. Cached thuộc input, reasoning thuộc output, không cộng hai lần.

Sau thời gian inactive, worker đổi `ACTIVE` thành `DORMANT`, không tự đóng topic. Tin phù hợp có thể mở lại episode. `MockMetaProvider` chỉ kiểm thử luồng, không đo chất lượng Meta. Bot Discord và khả năng chạy tải đồng thời chưa được kiểm chứng bằng các kiểm tra này.

## Quyền xử lý và sửa thủ công

Complete/fail/WAITING kiểm tra job còn CLAIMED, đúng owner và chưa hết lease ngay trong SQL. Mất lease khi complete làm rollback toàn bộ association/summary/action của lượt đó. ACK/fail action kiểm tra thêm lease_token riêng của từng lượt claim và cập nhật có điều kiện trước khi gắn thread vào topic. Dọn hàng đợi chỉ kết thúc lượt cuối đã hết lease, không giết lượt cuối đang chạy.

CREATE_THREAD hết retry trở thành DEAD; các action phụ thuộc được đánh dấu DependencyFailed khi quét claim, không treo PENDING mãi. Message mới không tự tạo CREATE_THREAD thay thế để vượt retry budget. Admin phải xác minh action đã thực hiện hay chưa rồi recover có audit.

Correction đổi association và dựng summary version từ snapshot do admin rà soát; giữ bản cũ, cập nhật index, hủy action PENDING và đánh dấu action lỗi cũ là superseded. Các topic liên quan `sync_paused=true`: worker vẫn ghi memory mới, nhưng không tạo thêm outbox và bot không claim action của chúng. Admin đối chiếu Discord với phiên bản DB hiện tại rồi resume-sync; không replay các action lịch sử. Chưa có heartbeat gia hạn lease hay bảo đảm exactly-once ở Discord: bot vẫn cần chống gửi trùng bằng action_id.
