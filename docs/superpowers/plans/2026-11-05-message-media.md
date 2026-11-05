# Chuyển link và ảnh vào Thread

Người dùng chọn sao chép link/ảnh, không phân tích ảnh hoặc mở trang web bằng AI. Giữ checkout có các thay đổi chưa commit; không commit hoặc migrate/restart production.

- [x] Lưu metadata attachment trong message và outbox/history qua JSON column mới, tương thích tin text cũ; kiểm chứng API/persistence/migration.
- [x] Bot nhận cả tin chỉ có attachment. Giữ nguyên content/link. Tin attachment-only dùng local routing: reply vào topic đã biết, nếu không có neo thì topic đính kèm riêng; không suy diễn nội dung ảnh hoặc gọi vision.
- [x] Khi delivery, lấy lại message gốc qua Discord SDK để làm mới URL, tải/re-upload từng file trong giới hạn guild, giữ tên/spoiler và receipt riêng mỗi attachment. Quá dung lượng/không còn nguồn thì gửi link kèm trạng thái rõ ràng; lỗi tạm thời retry. Kiểm tra guild để không lấy media từ server khác.
- [x] Test RED→GREEN: capture, API/DB, local routing, link giữ nguyên, ảnh-only, nhiều ảnh, retry không gửi trùng, fallback/error và lịch sử; chạy checks của repo, cập nhật API/setup docs.

Không thêm dependency; migration mới chỉ thêm metadata, không xóa dữ liệu. URL metadata không được dùng để tải tùy ý; file chỉ lấy từ attachment của message nguồn do Discord SDK trả về. Retention xóa cả metadata khỏi action hết hạn.

Kiểm chứng: regression theo phạm vi 85 passed; full suite 493 passed, 2 skipped; scoped Ruff/format và git diff --check qua. Test riêng bổ sung kiểm tra on_message nhận ảnh-only và BackendClient chuyển metadata. Phát hiện RED end-to-end: ảnh-only parent bị message_context lọc vì content rỗng; đã giữ marker metadata rõ ràng để bảo toàn reply anchor, không tạo mô tả giả cho ảnh. Các case URL bị cắt, spoiler fallback, retry sau ảnh thứ nhất và URL fallback dài đã RED→GREEN. API snapshot cập nhật theo schema hiện tại.

Tự rà soát, không có công cụ subagent trong phiên. Chưa gửi ảnh/tin Discord thật, chưa migrate/restart production. Triển khai runtime cần alembic upgrade head (20261105_0006), rồi restart API/worker/bot.
