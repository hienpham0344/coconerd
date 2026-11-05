import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql, sqlite

from backend.config import Settings
from backend.infrastructure.database.notifications import (
    ACTIONS_CHANNEL,
    WakeupSignal,
    listen_for_notifications,
    notify_transaction,
)
from backend.presentation.api.app import create_app


async def test_signal_broadcasts_and_removes_disconnected_subscribers():
    signal = WakeupSignal()
    async with signal.subscribe() as first, signal.subscribe() as second:
        signal.notify()
        assert first.is_set() and second.is_set()
        first.clear()
    signal.notify()
    assert not first.is_set()


@pytest.mark.parametrize("dialect, expected", [(postgresql.dialect(), 1), (sqlite.dialect(), 0)])
async def test_notify_uses_current_transaction_without_committing(dialect, expected):
    session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=dialect), execute=AsyncMock(), commit=AsyncMock()
    )
    await notify_transaction(session, ACTIONS_CHANNEL)
    assert session.execute.await_count == expected
    session.commit.assert_not_awaited()
    if expected:
        statement = session.execute.call_args.args[0]
        assert set(statement.compile().params.values()) == {ACTIONS_CHANNEL, ""}


def websocket_app():
    return create_app(
        Settings(
            _env_file=None,
            database_url="sqlite+aiosqlite:///:memory:",
            bot_api_key="bot-test-key",
            admin_api_key="admin-test-key",
        )
    )


def test_websocket_requires_bot_key_in_header():
    from starlette.websockets import WebSocketDisconnect

    app = websocket_app()
    with TestClient(app) as client:
        for path, headers in [
            ("/api/v1/actions/events", {}),
            ("/api/v1/actions/events", {"X-API-Key": "wrong"}),
            ("/api/v1/actions/events?api_key=bot-test-key", {}),
        ]:
            with (
                pytest.raises(WebSocketDisconnect),
                client.websocket_connect(path, headers=headers),
            ):
                pytest.fail("Unauthorized socket accepted")


def test_socket_wakes_on_committed_action_hint_and_cleans_up():
    app = websocket_app()
    with (
        TestClient(app) as client,
        client.websocket_connect(
            "/api/v1/actions/events", headers={"X-API-Key": "bot-test-key"}
        ) as socket,
    ):
        assert socket.receive_json() == {"type": "actions_available"}
        client.portal.call(app.state.action_signal.notify)
        assert socket.receive_json() == {"type": "actions_available"}


async def test_signal_does_not_lose_notification_between_checks():
    signal = WakeupSignal()
    async with signal.subscribe() as event:
        event.clear()
        signal.notify()
        await asyncio.wait_for(event.wait(), timeout=0.01)


async def test_listener_reconnects_broadcasts_and_releases_connection(monkeypatch, caplog):
    from backend.infrastructure.database import notifications

    connected = asyncio.Event()
    driver = MagicMock()
    driver.is_closed.return_value = False
    callbacks = []

    async def add_listener(channel, callback):
        callbacks.append(callback)
        assert channel == ACTIONS_CHANNEL
        if len(callbacks) == 1:
            raise OSError("sensitive-driver-details")
        connected.set()

    driver.add_listener = AsyncMock(side_effect=add_listener)
    driver.remove_listener = AsyncMock()
    connection = MagicMock()
    connection.get_raw_connection = AsyncMock(
        return_value=SimpleNamespace(driver_connection=driver)
    )
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    engine.connect.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.connect.return_value.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(notifications.asyncio, "sleep", AsyncMock())
    signal = WakeupSignal()
    async with signal.subscribe() as event:
        task = asyncio.create_task(listen_for_notifications(engine, ACTIONS_CHANNEL, signal))
        try:
            await asyncio.wait_for(connected.wait(), timeout=1)
            assert event.is_set()  # Reconnect scans work missed while disconnected.
            event.clear()
            callbacks[-1](None, 1, ACTIONS_CHANNEL, "")
            assert event.is_set()
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert driver.remove_listener.await_count == 2
    assert engine.connect.return_value.__aexit__.await_count == 2
    assert "sensitive-driver-details" not in caplog.text


async def test_sqlite_listener_keeps_polling_without_connecting():
    engine = MagicMock()
    engine.dialect.name = "sqlite"
    await listen_for_notifications(engine, ACTIONS_CHANNEL, WakeupSignal())
    engine.connect.assert_not_called()


async def test_postgres_notifies_only_after_commit(postgres_database_url):
    if not postgres_database_url:
        pytest.skip("Set COCONERD_TEST_POSTGRES_URL for real PostgreSQL notification integration")
    from contextlib import suppress

    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    engine = create_async_engine(postgres_database_url)
    signal = WakeupSignal()
    listener = asyncio.create_task(listen_for_notifications(engine, ACTIONS_CHANNEL, signal))
    try:
        async with signal.subscribe() as event:
            await asyncio.wait_for(event.wait(), timeout=5)
            event.clear()
            async with AsyncSession(engine) as session:
                await notify_transaction(session, ACTIONS_CHANNEL)
                await session.rollback()
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(event.wait(), timeout=0.05)
                await notify_transaction(session, ACTIONS_CHANNEL)
                assert not event.is_set()
                await session.commit()
                await asyncio.wait_for(event.wait(), timeout=5)
    finally:
        listener.cancel()
        with suppress(asyncio.CancelledError):
            await listener
        await engine.dispose()
