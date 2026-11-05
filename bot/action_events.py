"""Reconnect the backend wakeup socket without blocking HTTP polling."""

import asyncio
import logging
from contextlib import suppress
from urllib.parse import urlsplit, urlunsplit

import aiohttp

logger = logging.getLogger(__name__)


async def wait_for_actions(wakeup: asyncio.Event, timeout: float = 2.5) -> None:
    # Durable polling also recovers delayed retries and missed hints.
    with suppress(TimeoutError):
        await asyncio.wait_for(wakeup.wait(), timeout=timeout)


async def listen_action_events(backend, wakeup: asyncio.Event) -> None:
    backoff = 1.0
    while True:
        try:
            address = urlsplit(backend._build_url("api/v1/actions/events"))
            url = urlunsplit(address._replace(scheme="wss" if address.scheme == "https" else "ws"))
            session = await backend.get_session()
            async with session.ws_connect(
                url,
                headers={"X-API-Key": backend.api_key},
                heartbeat=20,
                receive_timeout=45,
                max_msg_size=1024,
            ) as socket:
                async for message in socket:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        data = message.json()
                        if isinstance(data, dict) and data.get("type") == "actions_available":
                            backoff = 1.0
                            wakeup.set()
                    elif message.type == aiohttp.WSMsgType.ERROR:
                        break
            logger.warning("Action socket disconnected; HTTP polling remains active")
        except Exception as exc:
            logger.warning(
                "Action socket unavailable; HTTP polling remains active",
                extra={"error_type": type(exc).__name__},
            )
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30.0)
