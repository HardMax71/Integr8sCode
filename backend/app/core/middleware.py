from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to limit request size, default 10MB"""

    def __init__(self, app, max_size_mb: int = 10):
        super().__init__(app)
        self.max_size_bytes = max_size_mb * 1024 * 1024

    async def dispatch(self, request: Request, call_next):
        if request.headers.get("content-length"):
            content_length = int(request.headers.get("content-length", 0))
            if content_length > self.max_size_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Request too large. Maximum size is {self.max_size_bytes/1024/1024}MB",
                )
        return await call_next(request)
