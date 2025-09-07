from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.core.logging import logger
from app.core.utils import get_client_ip
from app.domain.rate_limit import RateLimitAlgorithm, RateLimitStatus
from app.services.rate_limit_service import RateLimitService
from app.settings import Settings


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
    EXCLUDED_PATHS = frozenset({
        "/health",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/favicon.ico",
        "/api/v1/auth/login",  # Auth endpoints handle their own limits
        "/api/v1/auth/register",
        "/api/v1/auth/logout"
    })
    
    def __init__(
        self,
        app: FastAPI,
        rate_limit_service: RateLimitService,
        settings: Settings
    ):
        self.app = app
        self.rate_limit_service = rate_limit_service
        self.settings = settings
        self.enabled = settings.RATE_LIMIT_ENABLED
    
    async def __call__(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process request through rate limiting."""
        
        # Fast path: skip if disabled or excluded
        if not self.enabled or request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)
        
        # Extract identifier
        identifier = self._extract_identifier(request)
        username = self._extract_username(request)
        
        # Check rate limit
        status = await self._check_rate_limit(identifier, request.url.path, username)
        
        # Handle rate limit exceeded
        if not status.allowed:
            return self._rate_limit_exceeded_response(status)
        
        # Process request and add headers
        response = await call_next(request)
        self._add_rate_limit_headers(response, status)
        
        return response
    
    def _extract_identifier(self, request: Request) -> str:
        """Extract user ID or IP address as identifier."""
        # Check for authenticated user in request state
        if hasattr(request.state, "user") and request.state.user:
            return str(request.state.user.user_id)
        
        # Fall back to IP address for anonymous users
        return f"ip:{get_client_ip(request)}"
    
    def _extract_username(self, request: Request) -> Optional[str]:
        """Extract username if authenticated."""
        if hasattr(request.state, "user") and request.state.user:
            return getattr(request.state.user, "username", None)
        return None
    
    async def _check_rate_limit(
        self,
        identifier: str,
        endpoint: str,
        username: Optional[str]
    ) -> RateLimitStatus:
        """Check rate limit, with fallback on errors."""
        try:
            return await self.rate_limit_service.check_rate_limit(
                user_id=identifier,
                endpoint=endpoint,
                username=username
            )
        except Exception as e:
            # Log error but don't block request
            logger.error(f"Rate limit check failed for {identifier}: {e}")
            # Return unlimited status on error (fail open)
            return RateLimitStatus(
                allowed=True,
                limit=999999,
                remaining=999999,
                reset_at=datetime.now(timezone.utc) + timedelta(hours=1),
                retry_after=None,
                matched_rule=None,
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW
            )
    
    def _rate_limit_exceeded_response(self, status: RateLimitStatus) -> Response:
        """Create 429 response for rate limit exceeded."""
        headers = {
            "X-RateLimit-Limit": str(status.limit),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(int(status.reset_at.timestamp())),
            "Retry-After": str(status.retry_after or 60)
        }
        
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit exceeded",
                "retry_after": status.retry_after,
                "reset_at": status.reset_at.isoformat()
            },
            headers=headers
        )
    
    def _add_rate_limit_headers(self, response: Response, status: RateLimitStatus) -> None:
        """Add rate limit headers to response."""
        response.headers["X-RateLimit-Limit"] = str(status.limit)
        response.headers["X-RateLimit-Remaining"] = str(status.remaining)
        response.headers["X-RateLimit-Reset"] = str(int(status.reset_at.timestamp()))
