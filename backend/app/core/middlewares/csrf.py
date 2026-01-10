from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.security import SecurityService
from app.domain.user import CSRFValidationError


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

    def __init__(
        self,
        app: ASGIApp,
        security_service: SecurityService | None = None,
    ) -> None:
        self.app = app
        self.security_service = security_service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Lazily get service from Dishka container on first request
        if self.security_service is None:
            container = scope["app"].state.dishka_container
            async with container() as container_scope:
                self.security_service = await container_scope.get(SecurityService)

        request = Request(scope, receive=receive)

        try:
            # validate_csrf_from_request returns "skip" or the token if valid
            # raises CSRFValidationError if invalid
            self.security_service.validate_csrf_from_request(request)
            await self.app(scope, receive, send)

        except CSRFValidationError as e:
            response = JSONResponse(
                status_code=403,
                content={"detail": str(e)},
            )
            await response(scope, receive, send)
