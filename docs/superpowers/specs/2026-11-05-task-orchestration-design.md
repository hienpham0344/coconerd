# Điều phối task Meta

Người dùng đã chọn điều phối theo task sau đề xuất tách chat, phân loại và memory; mọi AI vẫn dùng Meta. Triển khai trong checkout hiện tại để giữ các thay đổi Railway và Meta-only chưa commit.

## Cách tiếp cận

- Chọn router xác định bằng code và profile riêng theo task. Giữ model mặc định `muse-spark-1.3`; cấu hình có thể chỉ định model Meta khác nhưng không tự khám phá hoặc chuyển provider.
- Không chọn một model manager phân công subagent: chưa có evaluation chứng minh lợi ích, và thêm lượt gọi sẽ cạnh tranh với ngân sách hai lượt/job.
- Không tách phân loại và cập nhật memory thành hai lượt gọi mặc định. Profile `topic_memory` thực hiện cả hai trong cùng structured response khi shortlist có facts cũ.

## Hợp đồng

`chat` chỉ được chọn tại luồng mention. Worker chọn `topic_memory` khi shortlist đã truy xuất chứa overview hoặc facts có nội dung; còn lại chọn `topic_classification`. Nội dung chat không được chỉ định task, provider hay cấu hình. Local rules vẫn chạy trước provider và không tốn lượt gọi.

Shared package `coconerd_ai` chỉ dùng thư viện chuẩn, không phụ thuộc bot, database, Discord hoặc backend. `TaskRouter` tạo immutable profiles; `TaskInvocation` chỉ chạy một lần, kiểm tra kích thước input trước dispatch, áp deadline cho HTTP/validation, không retry và không chuyển provider. Worker vẫn đặt chỗ lượt gọi bền vững qua `BudgetedProvider` và kiểm tra lease lúc commit.

`COCONERD_AGENT_MODE=task` là mặc định; `single` giữ thông số base cho mọi task nhưng vẫn kiểm tra cấu hình, input, deadline và output. `COCONERD_TASK_PROFILES` là JSON object, chỉ cho phép ba task và các trường `model`, `temperature`, `max_tokens`, `reasoning_effort`, `timeout_seconds`, `max_input_chars`. Sai tên, sai kiểu, bool thay số, NaN/Infinity hoặc vượt giới hạn phải bị từ chối trước request.

Giới hạn: model ID không rỗng/tối đa 200 ký tự; temperature 0–2; output 1–32768 tokens; timeout lớn hơn 0 và không quá 45 giây; input 1–131072 ký tự; reasoning effort theo các giá trị Meta đã hỗ trợ trong project. Default giữ model/token/effort hiện có; chat temperature 0.85/deadline 15 giây/input 24000 ký tự; hai task worker dùng temperature base/deadline 30 giây/input 64000 ký tự. Timeout do caller truyền chỉ được giảm deadline.

Backend dùng Settings đọc JSON từ cùng `.env` rồi áp profile sau lựa chọn guild/global/base hiện có. Task override là cấu hình operator rõ ràng, ưu tiên trên base đã chọn. Chat dùng cùng parser mà không cần cài backend; giữ hỗ trợ module và direct-script entrypoint.

Output structured giữ kiểm tra schema, evidence, shortlist, guild, trạng thái và memory replacement hiện có. Từ chối response bị cắt/refusal/finish reason bất thường; không ghi memory/action từ output lỗi. Ghi task, mode, profile version, model, token/effort/deadline và latency, không ghi prompt, key hay exception body. Trace thành công lưu thêm trong decision JSON, không cần migration.

## Kiểm chứng và phạm vi

Test parser/giới hạn/single-use/timeout/cancellation; HTTP giả lập cho từng profile, routing theo stored facts, không nghe chỉ dẫn đổi task trong chat; worker integration xác nhận trace và giới hạn hai lượt vẫn giữ. Chạy toàn bộ pytest cuối cùng, Ruff và diff checks. Không gọi API trả phí, không migrate/restart production, không gửi tin Discord, không commit/push trong task này.
