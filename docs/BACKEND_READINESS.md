# Backend hiện hỗ trợ gì và còn thiếu gì?

Đánh giá ngày **04/11/2026**, trên nhánh local `codex/topic-reliability`. Phân biệt ba việc: code đã có, hành vi đã kiểm tra offline và chất lượng khi chạy Meta/Discord thật. Test xanh không đồng nghĩa phân loại đúng ngoài thực tế.

## Kết luận

Backend đã có luồng lưu tin → tìm ngữ cảnh/topic → phân loại → cập nhật DB → giao action cho bot, kèm ngân sách model, lịch sử và đường sửa sai. Đợt reliability bổ sung confidence guard, memory có thể thay/xóa facts, retrieval tốt hơn, lease fencing và manual correction. **Chưa đủ dữ liệu để công bố accuracy**, và chưa có bot end-to-end chạy thật trong repo.

Theo rubric readiness ở cuối báo cáo, phần backend khoảng **70%**; bằng chứng cho toàn bộ bot khoảng **55%**. Đây là ước lượng kỹ thuật có trọng số, không phải phần trăm dòng code hay xác suất AI trả lời đúng. Không đánh giá tiến độ phần bot do thành viên khác giữ ngoài repo.

## Luồng chạy thật của hệ thống

1. Bot nhận từng Discord message gốc và gửi `POST /api/v1/messages`. Gửi riêng từng tin, giữ ID/reply/timestamp; không gộp nhiều người thành một đoạn mất nguồn.
2. API xác thực bot key, kiểm tra guild/channel allowlist và giới hạn request. Message và processing job được commit cùng nhau; `202` nghĩa là **đã nhận/lưu**, chưa có nghĩa phân loại xong. Retry cùng Discord message ID không tạo job mới.
3. Worker chạy ở tiến trình riêng, claim job có lease. `TopicTools` đọc reply chain, tin liên quan và topic index trong cùng guild; không cho LLM chạy SQL hoặc gọi Discord.
4. Local retrieval hợp nhất tối đa 30 kết quả từ index với 30 topic gần đây; batch summary reads và rank ra tối đa 5 cards. Context tối đa 6 tin/1.600 ký tự, tối đa 400 ký tự/tin.
5. Blank hoặc một số câu xác nhận không đủ tham chiếu được xử lý local với zero tokens. Ca còn lại đặt chỗ ngân sách rồi gọi Meta một lần để trả JSON Schema: existing/new/defer/irrelevant, confidence, evidence IDs và cập nhật memory.
6. Policy v4 kiểm tra target/evidence IDs, shortlist, confidence dưới 0.7, nhiều chủ đề, duplicate title và memory replacements. Service kiểm tra lại topic/trạng thái và memory đầy đủ trước khi ghi.
7. Association, AI decision, topic/episode, summary version và outbox được ghi trong cùng transaction. Nếu mất lease khi hoàn tất thì rollback kết quả lượt đó. Ngân sách model đã đặt chỗ không bị hoàn lại.
8. Bot claim outbox, thực thi Discord API và ACK/fail kèm `lease_token`. Action phụ thuộc CREATE_THREAD chỉ được phát khi thread đã tạo thành công. Bot phải tự chống lặp theo action_id.
9. Ca thiếu ngữ cảnh có thể WAITING tối đa 10 phút và chỉ xét lại một lần khi có clarification hợp lệ. Hết hạn vẫn giữ defer; không cố đoán để hoàn thành.
10. Admin có thể review/sửa sai bằng revision, snapshot memory và audit; đồng bộ Discord được pause đến khi đối chiếu xong. Xem [hướng dẫn thao tác](MANUAL_REVIEW.md).

## Những phần đã có

| Phần | Đã hỗ trợ | Bằng chứng/giới hạn |
| --- | --- | --- |
| Nhận và lưu tin | API key, allowlist, idempotent ingest, transaction message/job | Test HTTP và SQLite; chưa kiểm tra delivery từ bot thật |
| Phân loại | Topic cũ/mới, defer, irrelevant, structured output, reference guards | Offline regression và live smoke v4 tổng hợp; chưa có accuracy đại diện Discord |
| Context | Reply chain 3 cấp, context gần đây trong 10 phút, bounded evidence | Tin quá xa hoặc bị cắt có thể mất ý |
| Retrieval | Index lexical trong DB, alias Việt/Anh, tìm topic cũ, batch latest summaries | Không có dense embeddings; topic đúng vẫn có thể ngoài top 5 |
| Memory | Overview/fact lists, summary versions, source IDs, quoted replacements | Chưa có provenance theo từng fact hoặc kiểm chứng nghĩa |
| Tiết kiệm chi phí | Local rules, 1 call/pass, tối đa 2 reservations/message, bounded prompts, cache prefix | Không có số đo chứng minh tiết kiệm bao nhiêu % |
| Job/outbox | Lease fencing, retry budget, DEAD/dependency handling, action lease token | At-least-once; không bảo đảm exactly-once ở Discord |
| Sửa sai | Review/status, manual assignment, reviewed summary rebuild, audit/idempotency, pause/resume | Admin API; cần người/bot đối chiếu Discord thủ công |
| Topic lifecycle | ACTIVE/DORMANT/RESUMED/CLOSED, episodes | Chưa merge/split topic hay phát hiện drift tổng quát |
| Vận hành | Health, heartbeat, retention, log, migrations | Chưa có load/soak test hoặc dashboard/SLO production |

## Điểm mạnh

- **Lưu trước, AI sau:** lỗi provider không làm mất message đã được API nhận. Có thể kiểm tra job và quyết định để tìm nguyên nhân thay vì chỉ thấy một câu trả lời mất dấu vết.
- **Không buộc phải đoán:** defer là kết quả hợp lệ; confidence thấp, tham chiếu thiếu, nhiều chủ đề hoặc evidence bịa đều có cơ chế chặn.
- **Chi phí có trần:** retry không reset số lượt model; thao tác review/recovery không gọi model. Hệ thống hiện không tự tạo thêm một dàn agent tốn token.
- **Có đường sửa sai:** association sai không còn là dữ liệu bất biến không thể chữa. Sửa có revision, snapshot, lịch sử và kiểm soát action cũ.
- **Ranh giới code rõ:** domain, application service/policy/reducer, persistence ports và infrastructure; API/worker dùng cùng nghiệp vụ. Tách memory/projection/review khỏi message service, không thêm microservice hoặc dependency mới.

## Điểm yếu và tình huống nhận diện sai

| Tình huống | Vì sao vẫn khó | Hành vi hiện tại / việc cần tiếp |
| --- | --- | --- |
| “Cái đó sửa xong chưa?” không reply | Không xác định “cái đó” | Một số mẫu defer local; mẫu khác vẫn có thể bị model đoán sai |
| Hai dự án cùng nói “API, deadline, deploy” | Từ khóa gần giống nhưng khác mục tiêu | Ranker có thể đưa nhầm shortlist; cần benchmark hard negatives theo project/entity |
| “persistent storage engine” nói về DB | Paraphrase ít trùng chữ | Alias đã hỗ trợ một số cụm; câu ngoài từ điển vẫn yếu |
| Tin trả lời thread cũ nhưng đổi chủ đề | Reply là quan hệ hội thoại, không đảm bảo cùng topic | Prompt cho phép đổi chủ đề; chưa có bộ đánh giá đủ đại diện |
| Một tin nói bug API rồi rủ đi ăn | Một target chứa nhiều ý | `multiple_topics` dẫn tới defer; chưa tách một message thành nhiều assignment |
| Mỉa mai, phủ định, sửa ngày giờ | IDs/quotes có thật nhưng ý nghĩa đảo ngược | Structured output không giải được ngữ nghĩa; confidence cao vẫn có thể sai |
| Chuyển “thứ Năm” sang “thứ Sáu” | Memory cộng dồn có thể giữ cả hai | Replacement đã sửa khi model nhận ra và trích đúng; không tự suy ra mọi mâu thuẫn |
| Tin cực ngắn, viết tắt riêng của server | Không có nghĩa phổ quát | Hints local hữu hạn; cần dữ liệu thực và từ điển theo cộng đồng |
| Nhiều người nói xen nhau hoặc message đến trễ | Context được chọn có thể thuộc cuộc trò chuyện khác | Reply/author/time chỉ là tín hiệu; chưa có conversation disentanglement hoàn chỉnh |
| Ảnh, file, link, audio hoặc nội dung chỉ hiện trong embed | Backend chỉ nhận text | Chưa OCR/ASR/attachment extraction; không thể phân loại phần không được gửi |
| Sửa/xóa message Discord sau ingest | Snapshot hiện là immutable theo message ID | Gửi lại ID không cập nhật nội dung; chưa có edit/delete event protocol |
| Topic cùng guild nhưng khác channel có quyền khác nhau | Guild scope chưa tương đương Discord ACL | Bot phải bảo vệ quyền thread đích; server chưa nhận per-user/channel permission graph |
| Summary cũ chứa suy luận sai | IDs đúng không đồng nghĩa fact đúng | Human correction đã có; chưa có fact-level evidence/grounding tự động |
| Nhiều topic/tin, outbox lớn | SQLite single-writer, worker tuần tự, context hữu hạn | Cần benchmark tải, queue age và latency trước khi tăng số worker |

**Khi nào có khả năng nhận diện tốt hơn?** Tin nêu rõ project/mục tiêu (“Beta: chốt phát hành thứ Sáu”), topic đích có tên/memory khớp, reply rõ ràng, hội thoại chủ yếu một ý và các evidence cần thiết còn trong context. Đây là điều kiện thuận lợi, không phải bảo đảm đúng; model vẫn có thể sai tự tin.

**Khi nào hệ thống chủ động không gán?** Blank → irrelevant; các mẫu thiếu tham chiếu được nhận ra → defer; confidence assignment dưới 0.7, ID không hợp lệ, topic đóng/mất, memory replacement không khớp, hoặc model báo multiple_topics → defer. Sau lần xét lại, nếu vẫn không đủ bằng chứng thì giữ chưa gán để admin review.

## Lỗi vận hành có thể gặp

- Không có key hoặc key/provider/model không dùng được: ca cần Meta thất bại; ca local vẫn xử lý được. Live smoke sau đợt reliability đã xác nhận kết nối Meta với cấu hình/key lúc kiểm tra; không bảo đảm quota hoặc tính sẵn sàng về sau.
- Timeout, output bị cắt, JSON sai schema hoặc hết hai reservation: retry có giới hạn hoặc DEAD, không tạo assignment một phần. Output bị cắt không được nhận là kết quả hợp lệ.
- API và worker trỏ hai SQLite URL khác nhau hoặc quên migrate: nhận tin nhưng worker không thấy dữ liệu, hoặc lỗi schema. Chạy migration trước cả hai tiến trình.
- LLM chạy lâu hơn lease: kết quả không được commit. Chưa có cơ chế tự gia hạn lease; cần đo thời gian thực tế để đặt cấu hình phù hợp.
- Bot tạo thread thành công nhưng mất ACK: retry có thể tạo trùng nếu bot không chống lặp. Lease token chỉ bảo vệ DB trước ACK cũ, không hoàn tác side effect ở Discord.
- CREATE_THREAD lỗi hết attempts: action DEAD, phụ thuộc DEAD khi quét claim; cần recovery có xác minh, không tự tái tạo vượt budget.
- Admin sửa trong lúc worker/action đang chạy, dùng revision cũ hoặc snapshot nguồn sai: 409/422 và rollback, không cố ghi đè.
- Topic đang sync_paused: DB tiếp tục cập nhật nhưng Discord tạm không nhận action; đây là trạng thái có chủ đích, không phải worker hỏng.
- Retention xóa raw message/provenance hết hạn nhưng không tự viết lại nội dung summary lịch sử. Không nên mô tả retention hiện tại là xóa sạch mọi thông tin đã được tóm tắt.

## Mức độ hoàn thiện có thể bảo vệ bằng bằng chứng

Rubric dưới đây là đánh giá kỹ thuật chủ quan, công khai trọng số để có thể điều chỉnh; không lấy số test làm accuracy.

| Hạng mục để có bot hoàn chỉnh | Trọng số | Điểm readiness hiện tại |
| --- | ---: | ---: |
| API, DB, ingest và schema | 15 | 14 |
| Agent phân loại, context và retrieval | 25 | 18 |
| Memory và lịch sử | 10 | 8 |
| Recovery, review và sửa sai | 10 | 8 |
| Discord bot và tích hợp end-to-end | 20 | 0 — chưa có bằng chứng trong repo |
| Đánh giá chất lượng trên dữ liệu gán nhãn | 10 | 3 |
| Vận hành, tải, quan sát production | 10 | 4 |
| **Tổng** | **100** | **55** |

Bỏ phần bot ngoài repo, backend đạt 55/80 ≈ 69% theo cùng rubric. Phần chức năng đã viết nhiều hơn phần đã được xác minh ngoài thực tế. Không thể kết luận “AI đúng 70%” từ bảng này.

## Ưu tiên tiếp theo, lợi và hại

1. **Tích hợp bot và chạy pilot có giám sát.** Dùng action_id chống lặp, echo lease_token, quản lý thread/summary message, xử lý Discord rate limit/quyền truy cập và edit/delete events. Lợi: kiểm tra được đường đi thật. Hại/chi phí: cần thêm code bot và dữ liệu có kiểm soát; hiện chưa được triển khai tại đây theo phân công của người dùng.
2. **Bộ dữ liệu Discord có nhãn độc lập.** Đề xuất ban đầu 200–500 message đại diện, tách hội thoại/server giữa dev và holdout; đo precision của tin đã gán, recall@5 của retrieval, tỷ lệ defer, nhầm project, duplicate-topic, grounded summary và token/latency. Lợi: biết đúng chỗ cần sửa. Chi phí: cần người gán nhãn, privacy và ngân sách test model thật; số mẫu này là đề xuất, chưa được thu thập.
3. **Cải thiện retrieval theo lỗi đo được.** Nếu topic đúng thường ngoài shortlist, thêm entity/project anchors hoặc thử embeddings cục bộ/hybrid RAG có đối chứng. Lợi: sửa lỗi trước khi LLM suy luận. Hại: index/embedding version, vận hành và latency; chưa nên thêm vector DB chỉ vì tên kỹ thuật.
4. **Grounding theo từng fact và moderator UX.** Cần provenance cho từng fact nếu muốn tự rebuild memory khi xóa/sửa message, thêm giao diện sửa/merge/split và theo dõi sync_paused. Lợi: giảm công việc thủ công và lỗi lây vào memory. Hại: schema và logic sửa lịch sử phức tạp hơn; hiện snapshot do admin rà soát là lựa chọn bảo thủ.
5. **Đo tải và gia hạn lease có kiểm soát.** Đo queue age, p95 latency, lỗi khóa SQLite, DEAD/defer và backlog action. Lợi: biết khi nào cần nhiều worker hoặc PostgreSQL/queue chuyên dụng. Hại: thêm hạ tầng nếu làm quá sớm; chưa có cơ sở để đổi kiến trúc ngay.

Chưa ưu tiên thêm model reviewer/subagent trả phí: nó tăng số call nhưng không tự khắc phục thiếu context, retrieval sai hoặc nhãn benchmark yếu. Tiếp tục Meta-only và local tools trước; chỉ thêm bước model khi A/B evaluation chứng minh lợi ích đáng chi phí.

## Kiểm chứng và trạng thái triển khai

Kết quả kiểm tra mới nhất được ghi trong [TESTING.md](TESTING.md). Live smoke v3 trước đây chỉ có vài ca tổng hợp; không dùng để chứng minh prompt/policy v4 đạt accuracy nào. Các report lịch sử được giữ nguyên.

Live v4 sau đợt reliability: 8/9 snapshot khớp nhãn, gồm 2 ca local; ca memory còn lại bị cắt ở effort `low`/2.048 tokens. Chạy riêng ca đó với `minimal` và cùng giới hạn đã giữ fact cũ, sửa lịch và thêm phân công đúng qua reducer. Chưa kiểm tra persistence/Discord ở lượt live này, chưa đổi effort mặc định, chưa có tập nhãn độc lập; không tăng điểm readiness chỉ từ vài ca tổng hợp. Usage của lượt bị cắt chưa được runner lưu, nên tổng tokens/chi phí vẫn chưa đầy đủ.

Revision `20261104_0003` đã có code và được kiểm thử trên DB tạm. Checkout được phục hồi không có DB/key runtime cũ; chưa migrate DB chạy thật hoặc khởi động dịch vụ lâu dài. Đợt reliability offline không gọi Meta/Discord; sau đó đã cấu hình key local và chạy Meta theo phạm vi live smoke ở trên, vẫn chưa đăng nhập bot. Các sửa đổi mới còn ở nhánh local, chưa commit/push.
