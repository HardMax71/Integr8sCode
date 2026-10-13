from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.schemas_pydantic.common import ErrorResponse


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
            response = JSONResponse(ErrorResponse(status=413, detail=detail).model_dump(), status_code=413)
            await response(scope, receive, send)
            return

        await self.app(scope, _SizeLimitedReceive(receive, max_size, detail), send)


class _SizeLimitedReceive:
    """One request's ASGI receive, counting the body as it streams and failing once it passes the limit."""

    def __init__(self, receive: Receive, max_size: int, detail: str) -> None:
        self.receive = receive
        self.max_size = max_size
        self.detail = detail
        self.received = 0

    async def __call__(self) -> Message:
        message = await self.receive()
        if message["type"] == "http.request":
            self.received += len(message.get("body", b""))
            if self.received > self.max_size:
                # FastAPI turns any other exception raised while reading the body into a 400
                raise HTTPException(status_code=413, detail=self.detail)
        return message
