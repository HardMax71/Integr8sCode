from typing import Optional

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import Depends, HTTPException, Request

from app.api.dependencies import get_current_user_optional
from app.core.logging import logger
from app.core.utils import get_client_ip
from app.schemas_pydantic.user import User
from app.services.rate_limit_service import RateLimitService


@inject
async def check_rate_limit(
    request: Request,
    rate_limit_service: FromDishka[RateLimitService],
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> None:
    """
    Rate limiting dependency for API endpoints.
    
    Features:
    - User-based limits for authenticated users
    - IP-based limits for anonymous users (50% of normal limits)
    - Dynamic configuration from Redis
    - Detailed error responses
    
    Usage:
        @router.get("/endpoint", dependencies=[Depends(check_rate_limit)])
        async def my_endpoint():
            ...
    """
    # Determine identifier and multiplier
    if current_user:
        identifier = current_user.user_id
        username = current_user.username
        multiplier = 1.0
    else:
        identifier = f"ip:{get_client_ip(request)}"
        username = None
        multiplier = 0.5  # Anonymous users get half the limit
    
    # Check rate limit
    status = await rate_limit_service.check_rate_limit(
        user_id=identifier,
        endpoint=request.url.path,
        username=username
    )
    
    # Apply multiplier for anonymous users
    if not current_user and multiplier < 1.0:
        status.limit = max(1, int(status.limit * multiplier))
        status.remaining = min(status.remaining, status.limit)
    
    # Add headers to response (via request state)
    request.state.rate_limit_headers = {
        "X-RateLimit-Limit": str(status.limit),
        "X-RateLimit-Remaining": str(status.remaining),
        "X-RateLimit-Reset": str(int(status.reset_at.timestamp())),
        "X-RateLimit-Algorithm": status.algorithm
    }
    
    # Enforce limit
    if not status.allowed:
        logger.warning(
            f"Rate limit exceeded for {identifier} on {request.url.path}",
            extra={
                "identifier": identifier,
                "endpoint": request.url.path,
                "limit": status.limit,
                "algorithm": status.algorithm.value
            }
        )
        
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Rate limit exceeded",
                "retry_after": status.retry_after,
                "reset_at": status.reset_at.isoformat(),
                "limit": status.limit,
                "remaining": 0,
                "algorithm": status.algorithm.value
            },
            headers={
                "X-RateLimit-Limit": str(status.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(status.reset_at.timestamp())),
                "Retry-After": str(status.retry_after or 60)
            }
        )


# Alias for backward compatibility
DynamicRateLimiter = check_rate_limit
