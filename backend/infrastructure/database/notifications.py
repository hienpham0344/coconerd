"""Transactional PostgreSQL hints with reconnecting, process-local broadcast."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

logger = logging.getLogger(__name__)
JOBS_CHANNEL = "coconerd_jobs"
ACTIONS_CHANNEL = "coconerd_actions"


class WakeupSignal:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Event] = set()

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Event]:
        event = asyncio.Event()
        self._subscribers.add(event)
        try:
            yield event
        finally:
            self._subscribers.discard(event)

    def notify(self) -> None:
        for event in self._subscribers:
            event.set()


async def notify_transaction(session: AsyncSession, channel: str) -> None:
    """PostgreSQL delivers this empty hint only if the caller commits."""
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(select(func.pg_notify(channel, "")))


async def listen_for_notifications(engine: AsyncEngine, channel: str, signal: WakeupSignal) -> None:
    if engine.dialect.name != "postgresql":
        return
    backoff = 1.0
    while True:
        try:
            async with engine.connect() as connection:
                raw = await connection.get_raw_connection()
                driver = raw.driver_connection
                disconnected = asyncio.Event()

                def notified(*_args) -> None:
                    signal.notify()

                def terminated(*_args, event=disconnected) -> None:
                    event.set()

                driver.add_termination_listener(terminated)
                try:
                    await driver.add_listener(channel, notified)
                    backoff = 1.0
                    signal.notify()  # Re-scan durable work missed during disconnect.
                    await disconnected.wait()
                finally:
                    with suppress(Exception):
                        driver.remove_termination_listener(terminated)
                        if not driver.is_closed():
                            await driver.remove_listener(channel, notified)
            logger.warning("Queue notification connection closed", extra={"channel": channel})
        except Exception as exc:
            # URLs and driver exception bodies may contain credentials.
            logger.warning(
                "Queue notification listener unavailable; polling remains active",
                extra={"channel": channel, "error_type": type(exc).__name__},
            )
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30.0)
