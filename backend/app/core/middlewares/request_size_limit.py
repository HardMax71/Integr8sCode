from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


# --8<-- [start:RequestSizeLimitMiddleware]
class RequestSizeLimitMiddleware:
    """Middleware to limit request size, default 10MB.

    Checks Content-Length header when present for an early reject, and wraps
    the ASGI ``receive`` callable to count bytes as they stream — this
    catches chunked-transfer requests that omit Content-Length.
    """

    def __init__(self, app: ASGIApp, max_size_mb: int = 10) -> None:
        self.app = app
        self.max_size_bytes = max_size_mb * 1024 * 1024
    # --8<-- [end:RequestSizeLimitMiddleware]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        content_length_header = headers.get(b"content-length")

        if content_length_header:
            content_length = int(content_length_header)
            if content_length > self.max_size_bytes:
                response = JSONResponse(
                    status_code=413,
                    content={"detail": f"Request too large. Maximum size is {self.max_size_bytes / 1024 / 1024}MB"},
                )
                await response(scope, receive, send)
                return

        bytes_received = 0
        max_size = self.max_size_bytes
        exceeded = False

        async def receive_wrapper() -> Message:
            nonlocal bytes_received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                bytes_received += len(body)
                if bytes_received > max_size:
                    exceeded = True
                    raise _RequestTooLarge()
            return message

        try:
            await self.app(scope, receive_wrapper, send)
        except _RequestTooLarge:
            response = JSONResponse(
                status_code=413,
                content={"detail": f"Request too large. Maximum size is {max_size / 1024 / 1024}MB"},
            )
            await response(scope, receive, send)


class _RequestTooLarge(Exception):
    pass
