# Task Orchestration Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; no separate agent tool is available in this session.

**Goal:** Điều phối chặt chẽ chat, classification và memory với Meta-only và một lượt HTTP cho mỗi invocation.

**Architecture:** Shared package chứa router/profile và execution guard. Bot/Meta adapter giữ prompt và validator riêng; worker giữ durable reservation và transaction boundaries.

**Tech Stack:** Python 3.12, asyncio, existing OpenAI-compatible Meta SDK, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-11-05-task-orchestration-design.md`.

## Global Constraints

- Chỉ Meta; không dependency mới, migration, live request, production restart hoặc commit/push.
- Bảo toàn thay đổi chưa commit. Output 1–32768 tokens, timeout (0,45], input 1–131072 ký tự.
- Mỗi invocation một lần; worker vẫn tối đa hai reservation/job xuyên retries.

## Review Focus

- JSON typo, bool, NaN và cấu hình disabled vẫn phải được kiểm tra.
- Task/model không được chọn từ chỉ dẫn trong nội dung người dùng.
- Failed/cancelled invocation không được chạy lại; context phải đóng client.
- Single mode không được bỏ qua safety guard; deadline caller chỉ được giảm.
- Direct script và package installation phải thấy shared package mà không phụ thuộc backend.

### Task 1: Shared router và execution guard

**Files:** `coconerd_ai/__init__.py`, `coconerd_ai/task_routing.py`, `tests/backend/test_task_routing.py`, `pyproject.toml`.

**Interfaces:** `TaskKind`, `TaskRouter(...).resolve(task)`, `TaskRouter.topic_task(summaries)`, `TaskInvocation(profile).run(operation, input_chars, validate, timeout_seconds=None)`.

- [x] Viết test routing, immutable validated overrides, single mode, invalid input/config, single-use/error/timeout/cancellation.
- [x] Xác nhận RED, thêm implementation tối thiểu và package discovery; xác nhận GREEN.

### Task 2: Worker profiles và audit

**Files:** `backend/config.py`, `backend/infrastructure/meta_provider.py`, `backend/application/contracts.py`, `backend/application/services/messages.py`, `backend/logging_config.py`, `tests/backend/test_meta_provider.py`, `tests/backend/test_agent_worker.py`.

**Interfaces:** Settings `agent_mode`/`agent_task_profiles`; `ClassificationResult.task_route`; existing `ModelProvider.classify` unchanged.

- [x] Viết RED cho classification/memory profile routing, API payload/deadline, strict malformed output và trace.
- [x] Tích hợp router trong Meta adapter, giữ một call/response schema và hiện có reference/memory validators.
- [x] Xác nhận GREEN và worker reservation/lease regression tests.

### Task 3: Chat integration, docs và full validation

**Files:** `bot/ai.py`, `bot/main.py`, `tests/backend/test_bot_ai.py`, `.env.example`, `README.md`, `docs/MODEL_CONFIGURATION.md`, `docs/AGENT_WORKFLOW.md`, `docs/BOT_INTEGRATION.md`.

- [x] Viết RED cho chat profile/deadline/input guard, task injection và direct-script import.
- [x] Tích hợp shared router; giữ personality/history/clipping/static fallback và đóng client.
- [x] Cập nhật cấu hình/hướng dẫn, chạy focused tests, toàn bộ pytest, Ruff và diff checks.

## Evidence ledger

- Design đã đối chiếu với code: classification và memory là một structured call; budget đặt chỗ trước provider và giới hạn hai lượt/job. Triển khai theo lựa chọn task routing người dùng vừa yêu cầu.
- Không tạo worktree mới: feature phụ thuộc trực tiếp các thay đổi Meta-only/Railway chưa commit trong checkout này; không tách hoặc ghi đè chúng.

- Shared router: 42 passed sau RED→GREEN, gồm strict JSON/NaN/bool/overflow, deadline, single-use và cancellation.
- Integration/regression: 143 passed trước kiểm tra history; chat 31 passed sau khi sửa history vượt input budget bằng cách bỏ các turn cũ.
- Review bổ sung: startup validation không lộ key; worker chỉ log error class. Regression migration → log capture: 5 passed, 8 Alembic deprecation warnings.
- Các lần full suite trước bị chặn bởi module action_events đang được thêm song song, rồi test logger bị Alembic disable; không tính các lượt gián đoạn là thành công. Đã cô lập logger trong chính test, không sửa migration.
- Restricted runner dùng selector wakeup tối đa 10ms để asyncio thread callbacks tiến triển trong sandbox; không thay code runtime hoặc mở quyền mạng. Bộ duyệt escalation từng timeout, không có kết luận hành động không an toàn.
- Self-review: giữ nguyên dirty work; không có công cụ subagent độc lập để review. Chưa gọi Meta live, chưa restart service, chưa commit/push.

- Full snapshot trước: 468 passed, 2 skipped, 14 warnings; 1 failure tại test_provider_sends_grounded_hints_beside_original_in_one_request do fixture thiếu finish_reason khi collection. Fixture đã được cập nhật song song trong checkout; chạy riêng lại: 1 passed. Đang chạy lại full snapshot mới nhất.
- Runner cuối giảm selector polling từ 10ms xuống 1ms để giảm độ trễ wakeup của callback thread trong sandbox; không thay đổi code hoặc timeout của ứng dụng.
- Final full snapshot: `.venv/bin/python /tmp/coconerd-task-pytest.py -q --tb=short` → **469 passed, 2 skipped, 14 warnings, exit 0**, 137.21s. Warnings là `audioop` và Alembic `path_separator` deprecations.
- Ruff backend/shared/tests đã thay đổi và format check đạt; bot/ai.py lint giữ ngoại lệ E501 cho system prompt dài có sẵn, nội dung prompt được giữ nguyên. `git diff --check` đạt; hai JSON examples trong hướng dẫn parse được; shared package import được với Python `-S`.
- Hoàn tất implementation và kiểm chứng offline. Không migrate DB runtime, không gửi tin Discord, không gọi Meta live, không restart service hoặc commit/push.
