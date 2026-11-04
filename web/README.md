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

Mọi thay đổi trong bản trải nghiệm chỉ lưu cục bộ trong trình duyệt. Website không đọc hội thoại riêng, không quản trị server thật và không có endpoint đăng nhập. Các đường dẫn cũ `/app`, `/docs`, `/connect` vẫn hoạt động; `/faq`, `/support`, `/status` cùng mở trang Hướng dẫn. Thanh điều hướng chỉ giữ Tính năng, Hướng dẫn, Trải nghiệm và nút thêm bot; Dữ liệu & riêng tư nằm ở footer.

Ảnh bot nằm trên tiêu đề trang chủ; bảng màu kem ấm, than tối và olive đồng bộ với mascot. Cánh đồng hoa tiến chậm về phía người xem theo vòng lặp liên tục. Nút tạm dừng giữ nguyên cảnh; các khối nội dung xuất hiện khi cuộn, còn hiệu ứng chuyển trang bắt đầu sau khi nội dung được tải. Website tôn trọng tùy chọn giảm chuyển động của hệ điều hành.

## Link chính thức và trạng thái

Khi có link, sao chép `.env.example` thành `.env` rồi điền:

```dotenv
DISCORD_INVITE_URL=https://discord.com/oauth2/authorize?client_id=<ID_THAT>&scope=bot
DISCORD_SUPPORT_URL=https://discord.gg/<MA_MOI_THAT>
COCONERD_STATUS_URL=http://127.0.0.1:8000/api/v1/health
```

Đây chỉ là mẫu cú pháp, không phải lời mời thật. Hãy dán **toàn bộ link mời chính thức** của bot, gồm quyền cần thiết từ cấu hình Discord; website không tự đặt quyền quản trị. Có thể để trống cả ba biến. Khởi động lại web sau khi thay đổi.

`GET /api/site` chỉ trả hai link Discord đã kiểm tra. `GET /api/status` đọc endpoint health công khai nếu được cấu hình, chỉ trả trạng thái đã chuẩn hóa và thời gian kiểm tra. Kết quả lưu tối đa 30 giây, chờ tối đa 5 giây. Không gửi API key, cookie hay dữ liệu hội thoại tới endpoint đó. Các API đăng nhập và proxy quản trị cũ trả 404.

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

Suite kiểm tra cả routing của đường dẫn cũ/hộp thoại lời mời và HTTP: link công khai, URL không an toàn, việc loại bỏ đăng nhập/proxy quản trị, trạng thái chưa cấu hình, phản hồi lỗi và cache. Test routing TypeScript dùng cơ chế strip types tích hợp của Node.js. Bằng chứng kiểm tra giao diện nằm trong [docs/verification.md](docs/verification.md); ảnh xem trước nằm trong `docs/previews/`.

## Phạm vi nguồn

Website nằm trong `web/`, cùng repo với `../backend/` và `../bot/`. Các lệnh npm chạy trong `web/`; API, worker Python và cấu hình `pyproject.toml` vẫn chạy từ thư mục gốc repo. Website không tự tạo danh sách slash command chưa được xác minh.

`bridge/`, các script Python và `tests/test_bridge.py` từ hướng triển khai trước được giữ để tham khảo tích hợp nội bộ. Chúng **không được dùng bởi website công khai**, không tự chạy và không cần thiết để mở website. Có thể kiểm tra riêng bằng `npm run test:bridge` sau khi cài dependency Python của backend từ thư mục gốc repo. Script tự tìm `../.venv/bin/python` và backend ở thư mục cha của `web/`, độc lập với thư mục terminal hiện tại; có thể ghi đè bằng `COCONERD_PYTHON` và `COCONERD_BACKEND_SOURCE`. Test dùng database cô lập trong `.cache/pytest`.

Cảnh hoa và biểu tượng được dựng nguyên bản. Mascot tại `public/assets/coconerd-bot.png` là ảnh PNG trong suốt do người dùng cung cấp, được giữ nguyên và dùng trên trang chủ cùng bản trải nghiệm. Antonio dành cho tiêu đề tiếng Anh ở trang chủ; các trang phụ và tiêu đề tiếng Việt dùng Manrope. Font được tải từ Google Fonts, có font dự phòng. Website không có analytics hoặc quảng cáo.
