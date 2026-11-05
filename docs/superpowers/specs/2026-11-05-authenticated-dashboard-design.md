# Dashboard quản trị Coconerd có đăng nhập Discord

Ngày: 2026-11-05. Trạng thái: đã được người dùng duyệt ngày 2026-11-05; đã triển khai code và kiểm thử cục bộ.

## Yêu cầu đã xác nhận

Người dùng cần dashboard kết nối dữ liệu thật để xem và quản lý hội thoại bot.
Phải đăng nhập mới truy cập được. Dashboard phục vụ nhiều chủ server/quản trị
viên; mỗi người chỉ quản lý server mình có quyền.

## Hiện trạng đã kiểm tra

- Web dùng React/TypeScript/Vite và server Node.js; `#/demo` đọc dữ liệu mẫu,
  thay đổi mẫu lưu trong localStorage.
- Node hiện chỉ phục vụ API công khai `/api/site` và `/api/status`.
- `web/bridge/app.py` có các truy vấn tổng quan, danh sách server/chủ đề,
  nhưng chưa được API backend chính đăng ký.
- Backend đã có API xem topic, message, summary, cấu hình server/model,
  review/correction, trạng thái sync, resume-sync và recovery action.
- Backend hiện dùng bot/admin key; chưa xác thực danh tính người dùng Discord.
- Checkout có nhiều thay đổi backend/bot chưa commit. Giữ nguyên các thay đổi
  này, chỉ sửa phần cần cho dashboard; không commit/push hoặc deploy trong bước này.

## Phương án

1. **Đề xuất: Discord OAuth2, session riêng và kiểm tra quyền theo server.**
   Phù hợp mô hình nhiều server; người dùng dùng danh tính/quyền Discord hiện có.
   Cần cấu hình OAuth application và callback trên môi trường triển khai.
2. Mật khẩu chung không phân biệt được danh tính và quyền Discord của từng người,
   nên không đáp ứng yêu cầu đã xác nhận.
3. Tài khoản/mật khẩu riêng cho từng người cần thêm quản lý tài khoản và vẫn phải
   liên kết Discord để xác minh quyền; không có lợi cho yêu cầu hiện tại.

Người dùng đã duyệt bản thiết kế và phương án Discord OAuth2 trong cuộc trò chuyện.

## Phạm vi dashboard thật

Đường dẫn `#/app` dành cho dữ liệu thật. Trang giới thiệu và `#/demo` tiếp tục
phục vụ người ghé thăm; dữ liệu thật không bao giờ dùng mẫu làm phương án dự phòng.

- Đăng nhập/đăng xuất, hiển thị tài khoản, chọn server được phép quản trị.
- Tổng quan: số chủ đề, chủ đề hoạt động, tin nhắn và kênh đã cấu hình.
- Tìm kiếm/lọc/phân trang chủ đề; xem hội thoại gốc, tóm tắt và nguồn; đóng chủ đề.
- Review một tin nhắn: xem quyết định phân loại, revision và trạng thái xử lý;
  sửa topic đích hoặc bỏ gán, chỉnh đầy đủ memory của các topic bị ảnh hưởng.
- Theo dõi trạng thái sync, lịch sử action và lỗi; resume-sync/recover action
  theo hợp đồng hiện có, sau khi quản trị viên xác nhận đã đối chiếu Discord.
- Cấu hình từng server: bật/tắt nhận tin, kênh đầu vào/đầu ra, thời hạn lưu;
  cấu hình model chỉ trong server đang được phép quản trị.
- Làm mới dữ liệu và cập nhật định kỳ khi trang đang mở; xử lý rõ loading,
  hết phiên, thiếu quyền, chưa cấu hình, lỗi backend và xung đột revision/version.

Không thêm thao tác xóa toàn bộ dữ liệu, sửa cấu hình model toàn hệ thống,
gửi chat tùy ý, hoặc tự động replay action ngoài hợp đồng backend hiện tại.

## Quyền truy cập

Chính sách quyền đã được người dùng duyệt:

- Người dùng là chủ server hoặc có quyền Discord `ADMINISTRATOR` mới được đọc
  và sửa dữ liệu hội thoại của server đó. Chỉ có `MANAGE_GUILD` không đủ, vì quyền
  đó không bảo đảm được đọc mọi kênh riêng tư.
- Danh sách server là giao giữa các server người dùng có quyền trên Discord và
  các server đã cấu hình trong Coconerd. Không lộ danh sách server khác từ backend.
- Node kiểm tra quyền phía server cho mọi request dữ liệu thật và mọi mutation;
  không tin `guild_id`, `actor`, ID topic/message/action hoặc menu do browser gửi.
- Đọc quyền mới từ Discord trước mỗi mutation. Request đọc cũng cần quyền được
  xác minh; có thể dùng cache ngắn tối đa 30 giây để tránh gọi Discord quá mức.
  Discord lỗi hoặc không xác minh được quyền thì từ chối, không giữ quyền mặc định.
- Mọi resource phải thuộc đúng guild đã kiểm tra; đổi ID trên URL/body không thể
  truy cập topic, message hoặc action của guild khác.
- `actor` của thao tác quản trị do Node tạo thành `discord:<user_id>` từ phiên,
  không lấy nhãn danh tính do browser tự khai báo.

## Đăng nhập và phiên

- Dùng Authorization Code Grant với PKCE và scope tối thiểu `identify guilds`.
  Đăng nhập không yêu cầu người dùng đưa bot token hay admin key.
- Callback có URI cố định trong cấu hình; kiểm tra state, thời hạn, PKCE và issuer
  theo hợp đồng Discord. Return URL chỉ được phép là đường dẫn dashboard nội bộ.
- Browser chỉ nhận cookie chứa session ID ngẫu nhiên, `HttpOnly`, `SameSite=Lax`,
  `Path=/` và `Secure` trong production; HTTP local chỉ bật qua cấu hình development.
- Lưu hash session ID và dữ liệu phiên trong PostgreSQL qua backend nội bộ.
  OAuth access/refresh token được Node mã hóa trước khi lưu, dùng khóa môi trường
  riêng; không gửi token, client secret hoặc admin/bot key cho frontend.
- Phiên có hạn tuyệt đối 12 giờ; refresh token chỉ kéo dài token Discord trong
  thời hạn phiên này. Đăng xuất hủy phiên phía server và xóa cookie.
- Phiên phải hoạt động khi restart hoặc nhiều instance web dùng cùng DB/khóa.
- State OAuth được ràng buộc với browser, hết hạn ngắn và chống dùng lại.
- Mutation yêu cầu cùng origin và CSRF token; có giới hạn request/body/timeout.
  Không ghi credential, cookie hay mã OAuth vào log hoặc thông báo lỗi.

## Tích hợp với kiến trúc hiện có

- Giữ Node làm lớp OAuth/session và cổng truy cập dashboard cùng origin.
- Bổ sung các route đọc dashboard vào API backend chính, tái sử dụng logic bridge
  qua service/repository theo kiến trúc hiện có. Bridge vẫn có thể dùng cho test nội bộ.
- Backend quản lý persistence của phiên qua các route nội bộ dùng admin key;
  các route này không nằm trong danh sách Node cho browser truy cập.
- Node chỉ gọi danh sách route và method đã cho phép; không tạo proxy tùy ý.
  Bot/admin key chỉ được gắn vào request server-to-server cần thiết.
- Guild scope bắt buộc với cấu hình model; không cho browser bỏ guild để tác động
  cấu hình global. Danh sách channel phải thuộc đúng guild trước khi lưu settings.
- Review giữ nguyên request_id/revision/version và snapshot memory đầy đủ.
  HTTP 409 yêu cầu tải dữ liệu mới, không tự ghi đè hay tự retry mutation mới.
- Migration chỉ thêm bảng/index phục vụ session/OAuth state, không xóa dữ liệu;
  xác định lại Alembic head trước khi tạo để không xung đột migration đang có.

## Trải nghiệm quản trị

Giữ nhận diện hiện tại. Thêm lối vào dashboard và trang đăng nhập có nút
"Đăng nhập bằng Discord". Chưa đăng nhập không tải bất kỳ dữ liệu hội thoại nào.
Server không đủ quyền không xuất hiện; nếu quyền bị thu hồi khi đang dùng,
xóa dữ liệu đang hiển thị và báo cần kiểm tra lại quyền.

Chi tiết topic có phần hội thoại/tóm tắt và phần review/sync. Form correction
hiển thị rõ memory của cả topic cũ và topic mới cùng nguồn để tránh vô tình
xóa thông tin còn đúng. Resume/recover yêu cầu lý do và xác nhận đối chiếu thực tế;
dashboard không tuyên bố đã tự kiểm tra nội dung Discord.

## Cấu hình và triển khai

Cần cấu hình application/client ID, client secret, callback URL, khóa mã hóa
phiên và URL/key backend trong môi trường server; tài liệu chỉ chứa placeholder.
Không yêu cầu gửi secret trong chat hoặc commit vào repository.

Triển khai code, test, build và tài liệu cục bộ trong phạm vi này. Việc cấu hình
OAuth thật, chạy migration production hoặc deploy production cần bước riêng
được người dùng cho phép; không tuyên bố login thật đã chạy khi chưa kiểm thử.

## Kiểm chứng trước khi hoàn tất

- Test OAuth state/PKCE/callback, cookie, hết phiên/đăng xuất, session bền vững,
  từ chối khi Discord lỗi hoặc quyền bị thu hồi; credential không xuất hiện trong response.
- Test chưa đăng nhập, CSRF, sai origin, sai method, route ngoài allowlist,
  resource khác guild, actor giả, và truy cập model global đều bị chặn.
- Test tổng quan/topic/message/summary và cấu hình server bằng DB cô lập;
  review/correction/resume/recovery tuân thủ revision, version và tính idempotent.
- Chạy test web, production build và kiểm tra backend liên quan; test route demo
  vẫn dùng dữ liệu mẫu và không đọc/ghi dữ liệu thật.
- Kiểm tra giao diện desktop/mobile và trạng thái lỗi nếu môi trường preview cho phép.
  Kiểm thử OAuth với Discord thật cần cấu hình application; nêu rõ nếu chưa thực hiện.

## Tài liệu tham chiếu

- Discord OAuth2: https://docs.discord.com/developers/topics/oauth2
- Discord User Resource: https://docs.discord.com/developers/resources/user
- `docs/API_CONTRACT.md`, `docs/MANUAL_REVIEW.md`, `web/README.md`.

## Tự rà soát thiết kế

Đã đối chiếu với router backend, hợp đồng review và bridge hiện có. Code thực hiện
đúng phạm vi đã duyệt, kèm kiểm thử auth/guild isolation, migration, toàn suite
backend và browser bằng fixture. Chưa kiểm thử OAuth với Discord thật hoặc chạy
migration production trong phiên triển khai này.
