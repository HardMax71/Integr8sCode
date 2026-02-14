from datetime import datetime, timezone

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.utils import get_client_ip
from app.domain.rate_limit import RateLimitStatus
from app.domain.user import User
from app.services.rate_limit_service import RateLimitService
from app.settings import Settings


# --8<-- [start:RateLimitMiddleware]
class RateLimitMiddleware:
    """
    Middleware for rate limiting API requests.

    Features:
    - User-based limits for authenticated requests
    - IP-based limits for anonymous requests
    - Dynamic configuration via Redis
    - Graceful degradation on errors
    """

    # Paths exempt from rate limiting
    # --8<-- [start:excluded_paths]
    EXCLUDED_PATHS = frozenset(
        {
            "/health",
            "/metrics",
            "/docs",
            "/openapi.json",
            "/favicon.ico",
            "/api/v1/auth/login",  # Auth endpoints handle their own limits
            "/api/v1/auth/register",
            "/api/v1/auth/logout",
        }
    )
    # --8<-- [end:excluded_paths]
    # --8<-- [end:RateLimitMiddleware]

    def __init__(
        self,
        app: ASGIApp,
        rate_limit_service: RateLimitService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.app = app
        self.rate_limit_service = rate_limit_service
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]

        if path in self.EXCLUDED_PATHS:
            await self.app(scope, receive, send)
            return

        # Check if rate limiting is globally disabled via settings
        if self.settings is not None and not self.settings.RATE_LIMIT_ENABLED:
            await self.app(scope, receive, send)
            return

        # Try to get service if not initialized
        if self.rate_limit_service is None:
            asgi_app = scope.get("app")
            if asgi_app:
                container = asgi_app.state.dishka_container
                async with container() as container_scope:
                    self.rate_limit_service = await container_scope.get(RateLimitService)

            if self.rate_limit_service is None:
                await self.app(scope, receive, send)
                return

        # Build request object to access state
        request = Request(scope, receive=receive)
        user_id = self._extract_user_id(request)

        status = await self._check_rate_limit(user_id, path)

        if not status.allowed:
            response = self._rate_limit_exceeded_response(status)
            await response(scope, receive, send)
            return

        # Add rate limit headers to response
        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-RateLimit-Limit"] = str(status.limit)
                headers["X-RateLimit-Remaining"] = str(status.remaining)
                headers["X-RateLimit-Reset"] = str(int(status.reset_at.timestamp()))
            await send(message)

        await self.app(scope, receive, send_wrapper)

    # --8<-- [start:extract_user_id]
    def _extract_user_id(self, request: Request) -> str:
        user: User | None = request.state.__dict__.get("user")
        if user:
            return str(user.user_id)
        return f"ip:{get_client_ip(request)}"
    # --8<-- [end:extract_user_id]

    async def _check_rate_limit(self, user_id: str, endpoint: str) -> RateLimitStatus:
        # At this point service should be available; if not, allow request
        if self.rate_limit_service is None:
            return RateLimitStatus(
                allowed=True,
                limit=0,
                remaining=0,
                reset_at=datetime.now(timezone.utc),
            )

        return await self.rate_limit_service.check_rate_limit(user_id=user_id, endpoint=endpoint)

    def _rate_limit_exceeded_response(self, status: RateLimitStatus) -> JSONResponse:
        headers = {
            "X-RateLimit-Limit": str(status.limit),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(int(status.reset_at.timestamp())),
            "Retry-After": str(status.retry_after or 60),
        }

        return JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit exceeded",
                "retry_after": status.retry_after,
                "reset_at": status.reset_at.isoformat(),
            },
            headers=headers,
        )
