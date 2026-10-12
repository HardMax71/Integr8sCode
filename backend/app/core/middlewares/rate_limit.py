from dishka import AsyncContainer
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.security import SecurityService
from app.core.utils import get_client_ip
from app.domain.rate_limit import RateLimitStatus
from app.domain.user import InvalidCredentialsError
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

    # --8<-- [start:excluded_paths]
    EXCLUDED_PATHS = frozenset(
        {
            "/api/v1/auth/login",  # Auth endpoints handle their own limits
            "/api/v1/auth/register",
            "/api/v1/auth/logout",
        }
    )
    EXCLUDED_PREFIXES = ("/api/v1/health/",)
    # --8<-- [end:excluded_paths]
    # --8<-- [end:RateLimitMiddleware]

    def __init__(self, app: ASGIApp, container: AsyncContainer, settings: Settings) -> None:
        self.app = app
        self.container = container
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]

        if path in self.EXCLUDED_PATHS or path.startswith(self.EXCLUDED_PREFIXES):
            await self.app(scope, receive, send)
            return

        if not self.settings.RATE_LIMIT_ENABLED:
            await self.app(scope, receive, send)
            return

        rate_limit_service = await self.container.get(RateLimitService)
        security_service = await self.container.get(SecurityService)
        request = Request(scope, receive=receive)
        user_id = self._extract_user_id(request, security_service)

        status = await rate_limit_service.check_rate_limit(user_id=user_id, endpoint=path)

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
    @staticmethod
    def _extract_user_id(request: Request, security_service: SecurityService) -> str:
        """Key a signed-in request by its user id and any other by client IP.

        Only a token whose signature and expiry check out gives a user id, so a forged
        cookie can't pick another user's bucket or limits.
        """
        try:
            return security_service.decode_user_id(request.cookies.get("access_token", ""))
        except InvalidCredentialsError:
            return f"ip:{get_client_ip(request)}"

    # --8<-- [end:extract_user_id]

    def _rate_limit_exceeded_response(self, status: RateLimitStatus) -> JSONResponse:
        headers = {
            "X-RateLimit-Limit": str(status.limit),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(int(status.reset_at.timestamp())),
            "Retry-After": str(status.retry_after),
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
