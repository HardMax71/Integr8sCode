import structlog
from dishka import AsyncContainer
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.security import SecurityService
from app.domain.user import CSRFValidationError

logger = structlog.get_logger()


class CSRFMiddleware:
    """
    Middleware for CSRF protection using double-submit cookie pattern.

    This middleware validates that state-changing requests (POST, PUT, DELETE, PATCH)
    include a valid CSRF token in the X-CSRF-Token header that matches the csrf_token cookie.

    Requests are skipped if:
    - Method is safe (GET, HEAD, OPTIONS)
    - Path is an auth endpoint (login, register, logout)
    - Path is not under /api/
    - User is not authenticated (no access_token cookie)
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        container: AsyncContainer = scope["app"].state.dishka_container
        security_service: SecurityService = await container.get(SecurityService)

        request = Request(scope, receive=receive)

        try:
            security_service.validate_csrf_from_request(request)
            await self.app(scope, receive, send)

        except CSRFValidationError as e:
            logger.warning(
                "CSRF validation failed",
                path=request.url.path,
                method=request.method,
                reason=str(e),
            )
            response = JSONResponse(
                status_code=403,
                content={"detail": "CSRF validation failed"},
            )
            await response(scope, receive, send)
