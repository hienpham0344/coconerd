import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.config import Settings
from backend.worker import ConversationWorker


@pytest.mark.parametrize("wake_with_stop", [False, True])
async def test_worker_wakes_without_poll_delay_and_cancels_listener(monkeypatch, wake_with_stop):
    from backend import worker as worker_module

    started = asyncio.Event()
    stopped = asyncio.Event()
    captured = []

    async def listen(_engine, channel, signal):
        assert channel == "coconerd_jobs"
        captured.append(signal)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(worker_module, "listen_for_notifications", listen)
    worker = ConversationWorker(
        Settings(
            _env_file=None, database_url="sqlite+aiosqlite:///:memory:", worker_poll_seconds=30
        )
    )
    worker._heartbeat = AsyncMock()
    worker.prune_retained_data = AsyncMock(return_value=0)
    worker.mark_dormant_topics = AsyncMock(return_value=0)
    calls = 0

    async def process():
        nonlocal calls
        await started.wait()
        calls += 1
        if calls == 1 and not wake_with_stop:
            captured[0].notify()  # Arrives during claim, before the idle wait.
        else:
            await worker.stop()
        return False

    worker.process_once = process
    await asyncio.wait_for(worker.run(), timeout=1)
    assert calls == (1 if wake_with_stop else 2)
    assert stopped.is_set()
