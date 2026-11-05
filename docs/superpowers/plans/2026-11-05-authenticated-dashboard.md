# Authenticated Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Dashboard thật, đăng nhập Discord, chỉ owner/Administrator quản lý đúng guild.

**Architecture:** Node xử lý OAuth/PKCE, session, CSRF và guild authorization. Backend hiện có cung cấp persistence session mã hóa và dữ liệu dashboard; proxy chỉ cho phép các route cụ thể. React giữ demo và thêm chế độ live cùng form review/sync/settings.

**Tech Stack:** Node.js 22, React 19, TypeScript, FastAPI, SQLAlchemy, Alembic; không thêm dependency.

**Spec:** `docs/superpowers/specs/2026-11-05-authenticated-dashboard-design.md` (đã được người dùng duyệt).

## Global Constraints

- Chỉ owner hoặc Discord Administrator; MANAGE_GUILD đơn lẻ không đủ.
- Session tuyệt đối 12 giờ; cache quyền đọc tối đa 30 giây; mutation kiểm tra quyền mới.
- Không gửi token/key ra browser; OAuth state chống replay; CSRF và origin bắt buộc.
- Không tự động deploy, migrate production, commit/push hoặc sửa thay đổi cục bộ không liên quan.

## Review Focus

- Đổi guild/topic/action ID không thể vượt quyền, kể cả trong body.
- Thu hồi quyền, OAuth/Discord lỗi, hết phiên phải chặn và xóa nội dung cũ.
- Correction giữ toàn bộ memory/nguồn; request_id giữ nguyên khi retry cùng thao tác.
- OAuth callback replay và session dùng trên nhiều instance không bỏ qua xác thực.
- Cấu hình guild không được biến thành cấu hình global hoặc kênh của guild khác.

### Task 1: Persistence và route dashboard backend

**Files:** `backend/infrastructure/database/repositories/dashboard.py`, `backend/presentation/api/routers/dashboard.py`, models/app hiện có, migration `0007_dashboard_credentials`, `tests/backend/test_dashboard.py`.

**Interfaces:** `DashboardRepository(session)` cung cấp guild/settings/overview/topics và credential CRUD/consume. `create_router(repository, dependencies)` tạo route admin `/api/v1/admin/web/...`.

- [ ] Test route chính trả 401 khi thiếu admin key, trả dữ liệu guild-scoped có phân trang; credential có expiry và consume nguyên tử.
- [ ] Chạy `.venv/bin/python -m pytest tests/backend/test_dashboard.py -q`, xác nhận RED.
- [ ] Thêm model/migration chỉ-add và repository/router, đăng ký với app; bridge tái sử dụng route chính.
- [ ] Chạy lại test, bridge và migration SQLite cô lập; xác nhận GREEN.

### Task 2: Discord OAuth và session

**Files:** `web/server/auth.mjs`, `web/server/dashboard.mjs`, `web/server/handler.mjs`, `web/server/index.mjs`, `web/tests/dashboard.test.mjs`.

**Interfaces:** `createDashboardHandler(config)` trả handler `(req,res,url) -> Promise<boolean>`; `config.fetchImpl` dùng cho test. Auth `/auth/discord`, `/auth/discord/callback`, `/api/auth/session`, `/api/auth/logout`; credential API chỉ server-to-server.

- [ ] Test state/PKCE, callback sai/replay, cookie HttpOnly/Secure, mã hóa token, expiry/logout và session dùng bởi hai handler cùng storage.
- [ ] Chạy `node --test tests/dashboard.test.mjs`, xác nhận RED.
- [ ] OAuth code grant, AES-GCM storage, cookie opaque, refresh, rate limit và error sanitization.
- [ ] Chạy test auth và test server cũ, xác nhận GREEN.

### Task 3: Guild authorization và proxy cụ thể

**Files:** `web/server/dashboard.mjs`, `web/server/auth.mjs`, `web/tests/dashboard.test.mjs`.

**Interfaces:** `/api/dashboard/guilds`, `/api/dashboard/guilds/:guild/...` cho overview, topics/messages/summary, review/corrections, sync/resume/recovery, settings/model/channels.

- [ ] Test anonymous/CSRF/origin, owner/admin so với manager, thu hồi quyền, guild khác, actor giả, global model và route/method ngoài allowlist.
- [ ] Chạy test, xác nhận RED cho từng nhóm quyền.
- [ ] Kiểm tra quyền mọi request; map đường dẫn có guild bắt buộc; actor từ session; kiểm tra channel thuộc guild.
- [ ] Chạy toàn bộ web test, xác nhận GREEN.

### Task 4: Dashboard live và đăng nhập

**Files:** `web/src/data/live.ts`, `web/src/types.ts`, `web/src/pages/LiveDashboard.tsx`, `web/src/pages/Dashboard.tsx`, `web/src/pages/TopicDetail.tsx`, `web/src/routes.ts`, `web/src/App.tsx`, `web/src/components/PublicLayout.tsx`, `web/tests/routes.test.mjs`.

**Interfaces:** Live client giữ cùng API đọc với demo, thêm mutation; `LiveDashboard` bảo vệ bằng session và xóa dữ liệu khi 401/403; live deep link chứa guild ID.

- [ ] Test routing app/demo tách biệt và client không fallback sang dữ liệu mẫu; chạy RED.
- [ ] Thêm login/session shell, guild selector, live adapter, dữ liệu thật và refresh khi trang hiện; giữ demo.
- [ ] Type-check/build, chạy test routing/client, xác nhận GREEN.

### Task 5: Review, sync và settings

**Files:** `web/src/components/ReviewPanel.tsx`, `web/src/components/SyncPanel.tsx`, `web/src/components/GuildSettings.tsx`, `web/src/styles.css`, helper/test form.

**Interfaces:** Review snapshot theo `CorrectMessage`; sync/recover theo `ResumeTopicSync`/`RecoverAction`; model luôn có guild; form sinh và giữ request_id đến khi dữ liệu thao tác đổi.

- [ ] Test tạo snapshot, nguồn message, chọn topic đích, version/revision và request_id ổn định; chạy RED.
- [ ] Form đầy đủ dữ liệu thực, lý do/xác nhận recovery, phân trang history; hiển thị 409 và yêu cầu tải lại.
- [ ] Build và kiểm tra form/desktop/mobile nếu preview khả dụng; xác nhận GREEN.

### Task 6: Kiểm chứng và tài liệu

**Files:** `web/README.md`, `web/.env.example`, `web/docs/design.md`, verification và spec/plan.

- [ ] Ghi cấu hình OAuth/callback/session/backend bằng placeholder; hướng dẫn migration và production HTTPS, giới hạn kiểm thử thật.
- [ ] Chạy web tests/build, backend tests liên quan rồi suite backend; phân biệt lỗi baseline và regression.
- [ ] Rà diff riêng phần thay đổi dashboard, kiểm tra không secret/dependency/lockfile phát sinh.
- [ ] Ghi kết quả thực tế, nêu rõ chưa deploy và chưa login Discord thật nếu thiếu cấu hình.

## Execution ledger

- Ruling: thực thi inline trong checkout hiện tại để dùng đúng backend/bot chưa commit; không đổi nhánh, stash hay tạo worktree làm mất các thay đổi tích hợp. Không commit/push. Đây là lựa chọn triển khai sau khi thiết kế đã được duyệt, không yêu cầu duyệt lại.
- Pre-flight: Task 1 → Task 2 dùng credential kind/hash/payload/expiry; Task 2 → Task 3 session user/tokens/CSRF; Task 3 → Task 4/5 route guild-scoped. Không dùng proxy admin tổng quát hoặc route app làm demo.
- Task 1: complete — test dashboard/migration/architecture/API contract: 13 passed. SQLite migration giữ dữ liệu cũ và Alembic check đạt.
- Task 2/3: implemented — 7 test auth (OAuth/PKCE, mã hóa, CSRF, owner/admin, scope, logout/refresh CAS) đạt; thêm test adapter Vercel.
- Task 4/5: implemented — routing/review/live-client test đạt; production build đạt trước cập nhật nội dung privacy cuối.
- Task 6: in progress — docs, whole-suite rerun và browser QA bằng dữ liệu giả.
- Ruling: router nhận repository dependency từ composition root, không import infrastructure, để đáp ứng test kiến trúc hiện có.
- Ruling: README hiện xác định hosting Vercel; bổ sung catch-all Node Function và OAuth rewrites, dùng cùng handler với Node local. Chỉ chuẩn bị source, không deploy.
- Ruling: không có công cụ subagent trong phiên này; tự rà soát riêng diff dashboard và kiểm tra bằng test thay cho việc tuyên bố có reviewer độc lập.
- Baseline: web 11 passed ngoài sandbox; sandbox chặn localhost (EPERM). First full backend run: 498 passed, 2 skipped; lỗi snapshot/architecture do route mới đã được sửa và kiểm tra focused 13 passed.
