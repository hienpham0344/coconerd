# Điều phối task Meta

`COCONERD_AGENT_MODE=task` bật router xác định bằng code. Mặc định cả ba task dùng
`muse-spark-1.3`; mỗi task có profile, prompt và kiểm tra output riêng.

| Task | Điều kiện chọn | Output |
| --- | --- | --- |
| `chat` | Người dùng tag bot | Text hợp lệ, không refusal/truncated; hiển thị tối đa 1950 ký tự |
| `topic_classification` | Shortlist sau retrieval chưa có facts cũ | JSON decision và facts ban đầu, có schema/evidence checks |
| `topic_memory` | Topic trong shortlist có overview/facts cũ | Một JSON chung cho phân loại và memory delta, có kiểm tra replacements |

Title/topic ID hoặc summary rỗng không đủ để chọn memory. Nội dung người dùng không
được chỉ định task, model, provider hoặc giới hạn. Task memory vẫn có thể kết luận
`new` hoặc `defer`; sự hiện diện của memory không ép gộp topic. Local rules vẫn chạy
trước Meta, xử lý tin trống/một số xác nhận mơ hồ với zero calls.

## Cấu hình

Mặc định trong `.env`:

```dotenv
COCONERD_AGENT_MODE=task
COCONERD_TASK_PROFILES={}
```

Worker lấy base model/temperature/token limit theo thứ tự guild → global → môi trường.
Chat lấy base từ môi trường, temperature mặc định 0.85. Profile task áp dụng sau base;
`model` trong profile là override operator cho task đó ở mọi guild. Chỉ dùng model ID
đã được cấp trên tài khoản Meta; hệ thống không tự khám phá model. Key và endpoint
không được override trong profile; endpoint luôn là `https://api.meta.ai/v1`.

Ví dụ cấu hình riêng ngân sách từng task, cần đánh giá trên dữ liệu của bạn:

```dotenv
COCONERD_TASK_PROFILES='{"chat":{"max_tokens":1024,"timeout_seconds":12},"topic_classification":{"max_tokens":2048},"topic_memory":{"max_tokens":3072}}'
```

Trường được phép: `model`, `temperature`, `max_tokens`, `reasoning_effort`,
`timeout_seconds`, `max_input_chars`. Sai tên task/field, JSON trùng key, số dạng string,
bool thay số, NaN/Infinity và giá trị vượt giới hạn bị từ chối trước request.
Backend kiểm tra khi khởi động để tránh claim hàng loạt job với cấu hình sai.
Bot báo lỗi cấu hình và dùng câu meme tĩnh nếu không tạo được profile.

- Model ID: 1–200 ký tự, không whitespace.
- Temperature: 0–2; output: 1–32768 tokens, bao gồm reasoning tokens.
- Timeout: lớn hơn 0, tối đa 45 giây; mặc định chat 15 giây, worker 30 giây.
- Input: 1–131072 ký tự theo cấu hình; mặc định chat 24000, worker 64000.
  Số đo gồm system prompt và context/history được gửi, không phải token count.
  Chat bỏ lần lượt các lượt lịch sử cũ nhất để vừa ngân sách; không cắt tin hiện tại.
- Model/token/effort mặc định kế thừa base; effort `low`, output 2048 nếu chưa override.

`COCONERD_AGENT_MODE=single` dùng thông số base của từng luồng, bỏ qua override task.
Toàn bộ JSON vẫn được kiểm tra; input/output/deadline guards vẫn giữ nguyên.
Restart API, worker và bot sau khi đổi `.env` để dùng cùng cấu hình mới.
Khi cập nhật checkout có shared package mới, chạy lại `python -m pip install -e '.[dev]'`
trước khi dùng các console command đã cài từ phiên bản cũ.

## Giới hạn và lỗi

Mỗi `TaskInvocation` chỉ chạy một lần, kể cả khi lỗi, timeout hoặc bị hủy. Không có
SDK retry, provider fallback hay tự tăng ngân sách. Caller chỉ được giảm deadline;
worker còn giới hạn deadline theo lease được cấu hình, chừa tối đa 5 giây cho xử lý
tiếp. Lease vẫn được kiểm tra lúc commit; deadline không tự gia hạn lease.

Worker giữ tối đa hai call reservations trong toàn đời job, xuyên retries/reassessment.
Reservation được commit trước khi tạo provider: lỗi setup có thể mất một reservation
mà chưa gửi HTTP. Phân loại và memory dùng chung một response, không tiêu thêm lượt
chỉ vì chuyển sang profile memory. Cấu hình/input contract lỗi hoặc output bị cắt kết
thúc job `DEAD`; timeout/lỗi provider vẫn theo retry policy và trần hai lượt.

Task không ghi DB hoặc gọi Discord trực tiếp. Sau schema/reference/guild/topic/memory
checks, use case mới lưu kết quả và action trong transaction hiện có. Quote có thật
không chứng minh diễn giải của model đúng; human review vẫn cần thiết.

Các giới hạn trên áp dụng theo invocation/job; chưa có quota chi phí hoặc giới hạn
tổng request đồng thời toàn hệ thống. Không có lượt gọi model manager hay subagent.

## Quan sát và kiểm tra

Log task gồm tên task, model, mode, routing version, thông số giới hạn, status, loại
lỗi và latency. Không ghi prompt, response, key hoặc exception body. Decision lưu
thêm `payload.task_route` trong `ai_decisions` cùng usage hiện có; local rules có trace
rỗng. Không cần migration cho trường JSON bổ sung.

```bash
python -m pytest -q tests/backend/test_task_routing.py tests/backend/test_task_orchestration.py tests/backend/test_bot_ai.py tests/backend/test_agent_worker.py
```

Các test dùng HTTP giả lập và DB tạm. Kết quả offline không đo chất lượng, latency
hay chi phí Meta thực tế.
