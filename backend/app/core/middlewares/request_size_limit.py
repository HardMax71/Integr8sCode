from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RequestSizeLimitMiddleware:
    """Middleware to limit request size, default 10MB"""

    def __init__(self, app: ASGIApp, max_size_mb: int = 10) -> None:
        self.app = app
        self.max_size_bytes = max_size_mb * 1024 * 1024

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
                    content={
                        "detail": f"Request too large. Maximum size is {self.max_size_bytes / 1024 / 1024}MB"
                    }
                )
                await response(scope, receive, send)
                return
        
        await self.app(scope, receive, send)
