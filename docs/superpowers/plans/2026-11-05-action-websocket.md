# Action WebSocket Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đánh thức worker/bot ngay khi có job/action mới, giữ polling dự phòng.
**Architecture:** Transactional PostgreSQL NOTIFY → listener riêng mỗi process → WebSocket chỉ báo có action → HTTP claim/ACK hiện có.
**Tech Stack:** SQLAlchemy asyncpg, FastAPI WebSocket, aiohttp, asyncio.
**Spec:** `docs/superpowers/specs/2026-11-05-action-websocket-design.md`.

## Global Constraints

- Không thêm dependency, không ghi credential/prompt vào log/socket.
- Giữ thay đổi chưa commit; làm trực tiếp checkout hiện tại; không commit/restart production.
- Poll fallback bot 2,5 giây, worker theo `worker_poll_seconds`; heartbeat socket 20 giây.

## Review Focus

- Rollback không đánh thức consumer; tín hiệu không chứa dữ liệu hội thoại.
- API/worker khác process vẫn nhận notification, reconnect phải quét backlog.
- Auth thất bại không chấp nhận socket, key chỉ nằm trong header.
- Không mất wakeup khi event tới trong lúc claim/delivery; shutdown hủy task con.
- Không chờ 2,5 giây khi còn action; khi socket mất vẫn claim qua polling.

### Task 1: Notification và API socket

**Files:** Create notification port/infrastructure, WebSocket router và tests; modify API composition, job/action repositories.
**Interfaces:** `WakeupSignal.subscribe()` yields `asyncio.Event`; `WakeupSignal.notify()`; `listen_for_notifications(engine, channel, signal)`; `notify_transaction(session, channel)`.

- [x] Viết/run test RED cho subscription, publisher transaction, listener reconnect và socket auth/wakeup.
- [x] Triển khai publisher, listener và endpoint `/api/v1/actions/events`; SQLite fallback không LISTEN.
- [x] Chạy test task 1 GREEN, kiểm tra kiến trúc.

### Task 2: Worker và bot consumer

**Files:** Modify worker/bot main, create bot action event consumer; add tests, update integration/API docs.
**Interfaces:** `listen_action_events(backend, wakeup)` reconnect với backoff 1–30 giây; `wait_for_actions(wakeup, timeout=2.5)` fallback; task 1 cung cấp signal cho worker.

- [x] Viết/run test RED cho event wakeup, fallback, reconnect và backlog không nghỉ.
- [x] Nối worker signal và bot socket; hủy listener khi vòng xử lý dừng.
- [x] Chạy focused tests GREEN, suite backend, Ruff và diff checks; cập nhật tài liệu.

## Execution record

Thực hiện trực tiếp theo yêu cầu setup socket, không mở thêm vòng hỏi phương án. Không tạo worktree vì thay đổi cần tích hợp pipeline chưa commit tại checkout này.

Kiểm chứng: 12 test notification/API + architecture qua; 20 test bot/worker/delivery qua trước các thay đổi note đồng thời trong checkout. Test regression lỗi receipt sau tách outbox đã RED (NameError) → sửa import DeliveryError → GREEN. Ruff scoped, format và diff checks qua. Tự review, không có công cụ subagent trong phiên.

Suite toàn repo đã chạy: 445 passed, 3 failed, 2 skipped. Hai test log qua khi chạy riêng; Alembic fileConfig mặc định vô hiệu logger hiện có khi chạy chung. Test language normalization mock thiếu finish_reason, bị parser Meta hiện tại từ chối. Không sửa các phần logging/model ngoài phạm vi socket. Một lượt focused sau đó gặp thêm test note dài mới trong checkout (mất quyết định cuối do cắt embed), trong bot/delivery.py không do task socket sửa. Test PostgreSQL transaction thực chỉ chạy khi đặt COCONERD_TEST_POSTGRES_URL; chưa kiểm chứng Railway thật. Chưa restart dịch vụ runtime.
