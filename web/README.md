# Coconerd web

**Website:** [coconerd-2bn1.vercel.app](https://coconerd-2bn1.vercel.app/)

Website công khai cho bot Coconerd, **không cần đăng nhập**. Phong cách khu vườn đêm lấy cảm hứng từ tài liệu Fernhollow; cách chia mục tham khảo Jockie Music, không sao chép giao diện hay nội dung bot nhạc.

## Chạy trên máy

Cần Node.js 22.12+:

```bash
cd web # từ thư mục gốc repo coconerd
npm ci
npm run dev
```

Mở http://127.0.0.1:5173/. Không mở `index.html` qua `file://`; ứng dụng cần máy chủ để tải các thành phần. Không cần `.env`, API key hoặc database để xem website và dùng thử.

## Các trang

- Trang chủ: cảnh hoa Three.js tự dựng, tương tác con trỏ, chuyển động có thể dừng, âm thanh tùy chọn và nội dung giới thiệu.
- Tính năng: ba phần minh họa về kết nối hội thoại, tóm tắt và phạm vi xử lý, kèm liên kết đến ví dụ trong bản trải nghiệm.
- Hướng dẫn: ba bước bắt đầu, FAQ tìm kiếm tiếng Việt có/không dấu, kênh hỗ trợ và trạng thái dịch vụ gộp trong một trang.
- Thêm vào Discord: mở hộp thoại trên trang hiện tại, dùng link chính thức khi có; khi chưa có link, cho phép mở bản trải nghiệm. Escape đóng hộp thoại và trả lại vị trí cuộn.
- Trải nghiệm: chọn không gian mẫu, tìm/lọc chủ đề, đọc tóm tắt và hội thoại, thử khép lại chủ đề, đặt lại dữ liệu mẫu.
- Dữ liệu & riêng tư: giải thích phạm vi nhận tin, AI, lưu trữ và bản trải nghiệm.

Mọi thay đổi trong bản trải nghiệm chỉ lưu cục bộ trong trình duyệt. Trang công khai và demo không đọc hội thoại riêng. Dashboard dữ liệu thật ở `/#/app` yêu cầu đăng nhập Discord và quyền owner/Administrator của từng server. Các đường dẫn cũ `/docs`, `/connect` vẫn hoạt động; `/faq`, `/support`, `/status` cùng mở trang Hướng dẫn. Thanh điều hướng có Tính năng, Hướng dẫn, Trải nghiệm, Dashboard và nút thêm bot; Dữ liệu & riêng tư nằm ở footer.

Ảnh bot nằm trên tiêu đề trang chủ; bảng màu kem ấm, than tối và olive đồng bộ với mascot. Cánh đồng hoa tiến chậm về phía người xem theo vòng lặp liên tục. Nút tạm dừng giữ nguyên cảnh; các khối nội dung xuất hiện khi cuộn, còn hiệu ứng chuyển trang bắt đầu sau khi nội dung được tải. Website tôn trọng tùy chọn giảm chuyển động của hệ điều hành.

## Link chính thức và trạng thái

Khi có link, sao chép `.env.example` thành `.env` rồi điền:

```dotenv
DISCORD_INVITE_URL=https://discord.com/oauth2/authorize?client_id=<ID_THAT>&scope=bot
DISCORD_SUPPORT_URL=https://discord.gg/<MA_MOI_THAT>
COCONERD_STATUS_URL=http://127.0.0.1:8000/api/v1/health
```

Đây chỉ là mẫu cú pháp, không phải lời mời thật. Hãy dán **toàn bộ link mời chính thức** của bot, gồm quyền cần thiết từ cấu hình Discord; website không tự đặt quyền quản trị. Có thể để trống cả ba biến. Khởi động lại web sau khi thay đổi.

`GET /api/site` chỉ trả hai link Discord đã kiểm tra. `GET /api/status` đọc endpoint health công khai nếu được cấu hình, chỉ trả trạng thái đã chuẩn hóa và thời gian kiểm tra. Kết quả lưu tối đa 30 giây, chờ tối đa 5 giây. Không gửi API key, cookie hay dữ liệu hội thoại tới endpoint đó. Các proxy quản trị tổng quát cũ vẫn trả 404. Dashboard sử dụng API riêng có session, CSRF và kiểm tra quyền theo server.

## Bản production cục bộ

```bash
npm run build
npm start
```

Máy chủ cục bộ mặc định chỉ lắng nghe `127.0.0.1:5173`. Website công khai đã có bản triển khai trên Vercel ở liên kết đầu trang.

## Kiểm tra

```bash
npm test
npm run build
```

Suite kiểm tra cả routing của đường dẫn cũ/hộp thoại lời mời và HTTP: link công khai, URL không an toàn, việc chặn proxy quản trị tổng quát, trạng thái chưa cấu hình, phản hồi lỗi và cache. Test routing TypeScript dùng cơ chế strip types tích hợp của Node.js. Bằng chứng kiểm tra giao diện nằm trong [docs/verification.md](docs/verification.md); ảnh xem trước nằm trong `docs/previews/`.

## Phạm vi nguồn

Website nằm trong `web/`, cùng repo với `../backend/` và `../bot/`. Các lệnh npm chạy trong `web/`; API, worker Python và cấu hình `pyproject.toml` vẫn chạy từ thư mục gốc repo. Website không tự tạo danh sách slash command chưa được xác minh.

`bridge/`, các script Python và `tests/test_bridge.py` từ hướng triển khai trước được giữ để tham khảo tích hợp nội bộ. Bridge không cần chạy riêng cho dashboard: API chính đã đăng ký các route đọc quản trị. Launcher bridge được giữ tương thích cho kiểm thử nội bộ. Có thể kiểm tra riêng bằng `npm run test:bridge` sau khi cài dependency Python của backend từ thư mục gốc repo. Script tự tìm `../.venv/bin/python` và backend ở thư mục cha của `web/`, độc lập với thư mục terminal hiện tại; có thể ghi đè bằng `COCONERD_PYTHON` và `COCONERD_BACKEND_SOURCE`. Test dùng database cô lập trong `.cache/pytest`.

Cảnh hoa và biểu tượng được dựng nguyên bản. Mascot tại `public/assets/coconerd-bot.png` là ảnh PNG trong suốt do người dùng cung cấp, được giữ nguyên và dùng trên trang chủ cùng bản trải nghiệm. Antonio dành cho tiêu đề tiếng Anh ở trang chủ; các trang phụ và tiêu đề tiếng Việt dùng Manrope. Font được tải từ Google Fonts, có font dự phòng. Website không có analytics hoặc quảng cáo.

## Dashboard dữ liệu thật và Discord OAuth

Mở `/#/app`, đăng nhập Discord, chọn server đã được cấu hình trong Coconerd.
Chỉ chủ server hoặc người có quyền **Administrator** được đọc/sửa hội thoại;
Manage Server riêng lẻ không đủ quyền xem toàn bộ dữ liệu. Dashboard có tổng quan,
chủ đề/hội thoại/tóm tắt, review/correction, trạng thái sync/recovery và cấu hình
kênh, thời hạn lưu, model riêng cho từng server. Demo vẫn nằm ở `/#/demo`.

1. Triển khai backend có migration mới; áp dụng `alembic upgrade head` theo quy trình
   vận hành backend. Migration `20261105_0007` chỉ thêm bảng credential/index.
   Không trỏ môi trường test vào database đang vận hành.
2. Tạo/cấu hình OAuth2 application trong Discord Developer Portal. Đăng ký đúng
   `https://<domain-web>/auth/discord/callback`; flow dùng code grant + PKCE,
   chỉ xin `identify guilds`.
3. Điền các biến **phía server** trong `.env.example`: `DISCORD_CLIENT_ID`,
   `DISCORD_CLIENT_SECRET`, `DISCORD_REDIRECT_URI`, `DASHBOARD_SESSION_SECRET`,
   `BACKEND_BASE_URL`, `COCONERD_BOT_API_KEY`, `COCONERD_ADMIN_API_KEY`,
   `DISCORD_BOT_TOKEN`. Bot token dùng để đọc/kiểm tra danh sách kênh. Không thêm
   tiền tố `VITE_`, không commit giá trị thật và không gửi secret trong chat.
4. Khóa phiên phải ngẫu nhiên mạnh, ít nhất 32 bytes và giống nhau giữa các instance.
   Token Discord được mã hóa AES-GCM; browser chỉ giữ session ID trong cookie
   HttpOnly/SameSite=Lax/Secure. Hash ID và payload mã hóa được lưu ở backend,
   không phụ thuộc bộ nhớ instance web. Phiên hết hạn tuyệt đối sau 12 giờ.
5. Vercel: chọn project root `web`, giữ Vite build, cấu hình các biến trên trong
   Environment Variables rồi triển khai theo quy trình riêng. `api/[...path].mjs`
   cung cấp Node Function; `vercel.json` chuyển OAuth callback đến function.
   Bản build static đơn thuần không cung cấp các API đăng nhập/quản trị.

Local có thể đặt `DISCORD_REDIRECT_URI=http://127.0.0.1:5173/auth/discord/callback`
và `COCONERD_WEB_ALLOW_HTTP=true`; cần đăng ký callback local trong Discord.
HTTP chỉ được phép trên loopback khi bật tùy chọn này. Production phải dùng HTTPS.
Thiếu cấu hình thì khu vực quản trị đóng và báo chưa sẵn sàng; không dùng dữ liệu mẫu
để thay cho dữ liệu thật.

Node chỉ cho phép danh sách API cụ thể, kiểm tra guild cho từng request, xác minh
quyền mới trước mỗi mutation và cache quyền đọc tối đa 30 giây. Mutation cần
cùng origin và CSRF token. Model global, proxy tùy ý và credential API nội bộ
không thể truy cập qua dashboard. Actor review do session xác định.

Correction yêu cầu đầy đủ memory/nguồn của các topic bị ảnh hưởng và giữ revision/version.
HTTP 409 yêu cầu tải lại rồi rà soát; retry cùng nội dung giữ request_id. Sau correction,
đối chiếu bản sao Discord rồi mới resume-sync/recover: dashboard không tự xác minh
side effect trên Discord và không tự replay lịch sử.
