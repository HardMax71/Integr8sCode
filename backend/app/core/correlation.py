import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class CorrelationMiddleware:
    CORRELATION_HEADER = "X-Correlation-ID"

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        correlation_id = headers.get("x-correlation-id") or f"req-{uuid.uuid4().hex}"

        scope.setdefault("state", {})["correlation_id"] = correlation_id

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[self.CORRELATION_HEADER] = correlation_id
            await send(message)

        await self.app(scope, receive, send_wrapper)
