from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


# --8<-- [start:RequestSizeLimitMiddleware]
class RequestSizeLimitMiddleware:
    """Middleware to limit request size, default 10MB.

    Checks Content-Length header when present for an early reject, and wraps
    the ASGI ``receive`` callable to count bytes as they stream. This
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

        max_size = self.max_size_bytes
        detail = f"Request too large. Maximum size is {max_size / 1024 / 1024}MB"

        headers = dict(scope["headers"])
        content_length_header = headers.get(b"content-length")

        if content_length_header and int(content_length_header) > max_size:
            response = JSONResponse(status_code=413, content={"detail": detail})
            await response(scope, receive, send)
            return

        bytes_received = 0

        async def receive_wrapper() -> Message:
            nonlocal bytes_received
            message = await receive()
            if message["type"] == "http.request":
                bytes_received += len(message.get("body", b""))
                if bytes_received > max_size:
                    # FastAPI turns any other exception raised while reading the body into a 400
                    raise HTTPException(status_code=413, detail=detail)
            return message

        await self.app(scope, receive_wrapper, send)
