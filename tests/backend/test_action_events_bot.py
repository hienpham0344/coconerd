import asyncio
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from bot.action_events import listen_action_events, wait_for_actions
from bot.outbox import process_outbox_actions


async def test_wait_wakes_immediately_and_keeps_polling_without_socket():
    wakeup = asyncio.Event()
    wakeup.set()
    await asyncio.wait_for(wait_for_actions(wakeup, timeout=10), timeout=0.1)
    wakeup.clear()
    await wait_for_actions(wakeup, timeout=0.001)


async def test_bot_uses_authenticated_wss_and_only_action_hints_wake_consumer():
    wakeup = asyncio.Event()
    observed = asyncio.Event()

    class Socket:
        def __aiter__(self):
            return self.messages()

        async def messages(self):
            yield SimpleNamespace(type=aiohttp.WSMsgType.TEXT, json=lambda: {"type": "heartbeat"})
            assert not wakeup.is_set()
            yield SimpleNamespace(
                type=aiohttp.WSMsgType.TEXT, json=lambda: {"type": "actions_available"}
            )
            observed.set()
            await asyncio.Event().wait()

    session = MagicMock()
    session.ws_connect.return_value.__aenter__ = AsyncMock(return_value=Socket())
    session.ws_connect.return_value.__aexit__ = AsyncMock(return_value=False)
    backend = SimpleNamespace(
        _build_url=lambda path: "https://backend.example/prefix/" + path,
        api_key="test-key",
        get_session=AsyncMock(return_value=session),
    )
    task = asyncio.create_task(listen_action_events(backend, wakeup))
    try:
        await asyncio.wait_for(observed.wait(), timeout=1)
        assert wakeup.is_set()
        assert session.ws_connect.call_args.args == (
            "wss://backend.example/prefix/api/v1/actions/events",
        )
        assert session.ws_connect.call_args.kwargs["headers"] == {"X-API-Key": "test-key"}
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    session.ws_connect.return_value.__aexit__.assert_awaited_once()


async def test_socket_errors_reconnect_without_stopping_polling(monkeypatch, caplog):
    from bot import action_events

    retry = asyncio.Event()
    session = MagicMock()
    session.ws_connect.return_value.__aenter__ = AsyncMock(side_effect=OSError("private-details"))
    backend = SimpleNamespace(
        _build_url=lambda path: "http://backend/" + path,
        api_key="test-key",
        get_session=AsyncMock(return_value=session),
    )
    original_sleep = asyncio.sleep

    async def sleep(delay):
        if session.ws_connect.call_count >= 2:
            retry.set()
            await asyncio.Event().wait()
        await original_sleep(0)

    monkeypatch.setattr(action_events.asyncio, "sleep", sleep)
    task = asyncio.create_task(listen_action_events(backend, asyncio.Event()))
    try:
        await asyncio.wait_for(retry.wait(), timeout=1)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    assert session.ws_connect.call_count == 2
    assert "private-details" not in caplog.text


@pytest.mark.parametrize("actions", [[[{"action_id": "a", "type": "COPY_MESSAGE"}]], [[]]])
async def test_outbox_drains_without_sleep_and_cancels_socket(monkeypatch, actions):
    from bot import outbox

    wakeup = asyncio.Event()
    watcher_stopped = asyncio.Event()

    async def watch(_backend, event):
        assert event is wakeup
        try:
            await asyncio.Event().wait()
        finally:
            watcher_stopped.set()

    closed = False

    async def claim(*args, **kwargs):
        nonlocal closed
        await asyncio.sleep(0)
        if actions:
            return actions.pop(0)
        closed = True
        return []

    bot = SimpleNamespace(
        wait_until_ready=AsyncMock(),
        backend=SimpleNamespace(
            claim_actions=AsyncMock(side_effect=claim),
            complete_action=AsyncMock(return_value=True),
        ),
        worker_id="test-worker",
        is_closed=lambda: closed,
        _action_wakeup=wakeup,
    )
    delivery = SimpleNamespace(deliver=AsyncMock(return_value={}))
    wait = AsyncMock()
    monkeypatch.setattr(outbox, "listen_action_events", watch)
    monkeypatch.setattr(outbox, "wait_for_actions", wait)
    monkeypatch.setattr(outbox, "TopicDelivery", lambda *args: delivery)
    await process_outbox_actions(bot)
    assert wait.await_count == (1 if delivery.deliver.await_count == 0 else 0)
    assert watcher_stopped.is_set()


async def test_backend_receipt_failure_keeps_delivery_error_after_outbox_extraction():
    from bot.delivery import DeliveryError
    from bot.main import BackendClient

    backend = BackendClient("http://backend", "test-key")
    session = MagicMock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=SimpleNamespace(status=503))
    session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    backend.get_session = AsyncMock(return_value=session)
    with pytest.raises(DeliveryError):
        await backend.get_delivery_receipt("receipt")
