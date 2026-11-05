"""Authenticated wakeup-only WebSocket; claims and ACKs remain HTTP operations."""

import asyncio
from contextlib import suppress

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status

from backend.presentation.api.dependencies import ApiDependencies
from backend.presentation.api.security import verify_key

HEARTBEAT_SECONDS = 20.0


def create_router(dependencies: ApiDependencies) -> APIRouter:
    router = APIRouter()

    @router.websocket("/api/v1/actions/events")
    async def action_events(socket: WebSocket) -> None:
        try:
            verify_key(
                dependencies.settings.bot_api_key, socket.headers.get("X-API-Key"), "Bot API"
            )
        except HTTPException:
            await socket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        async with dependencies.action_notifications.subscribe() as wakeup:
            await socket.accept()

            async def send_events() -> None:
                await socket.send_json({"type": "actions_available"})
                while True:
                    try:
                        await asyncio.wait_for(wakeup.wait(), timeout=HEARTBEAT_SECONDS)
                        wakeup.clear()
                        kind = "actions_available"
                    except TimeoutError:
                        kind = "heartbeat"
                    await socket.send_json({"type": kind})

            sender = asyncio.create_task(send_events())
            receiver = asyncio.create_task(socket.receive())
            try:
                done, _ = await asyncio.wait(
                    (sender, receiver), return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    task.result()
            except (WebSocketDisconnect, OSError):
                pass
            finally:
                for task in (sender, receiver):
                    task.cancel()
                for task in (sender, receiver):
                    with suppress(asyncio.CancelledError, WebSocketDisconnect, OSError):
                        await task

    return router
