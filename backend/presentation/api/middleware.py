"""Bound request bodies before dispatch, preserving their ASGI receive stream."""

from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBoundaryMiddleware:
    def __init__(self, app: ASGIApp, max_request_bytes: int) -> None:
        self.app = app
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        request_id = headers.get("X-Request-ID") or str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_response(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers["X-Content-Type-Options"] = "nosniff"
                response_headers["X-Request-ID"] = request_id
            await send(message)

        content_length = headers.get("content-length")
        if content_length:
            try:
                too_large = int(content_length) > self.max_request_bytes
            except ValueError:
                await Response(
                    "Invalid Content-Length", status_code=400, headers={"X-Request-ID": request_id}
                )(scope, receive, send_response)
                return
            if too_large:
                await Response(status_code=413, headers={"X-Request-ID": request_id})(
                    scope, receive, send_response
                )
                return
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_request_bytes:
                await Response(status_code=413, headers={"X-Request-ID": request_id})(
                    scope, receive, send_response
                )
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": b"".join(chunks), "more_body": False}

        await self.app(scope, replay, send_response)
