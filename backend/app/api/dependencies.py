from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import HTTPException, Request

from app.domain.user import User
from app.services.auth_service import AuthService


async def check_request_size(request: Request) -> None:
    """Reject requests whose body exceeds MAX_REQUEST_SIZE_MB from settings."""
    settings = request.app.state.settings
    max_bytes = settings.MAX_REQUEST_SIZE_MB * 1024 * 1024
    body = await request.body()
    if len(body) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Request too large. Maximum size is {settings.MAX_REQUEST_SIZE_MB}MB",
        )


@inject
async def current_user(request: Request, auth_service: FromDishka[AuthService]) -> User:
    """Get authenticated user."""
    return await auth_service.get_current_user(request)


@inject
async def admin_user(request: Request, auth_service: FromDishka[AuthService]) -> User:
    """Get authenticated admin user."""
    return await auth_service.get_admin(request)
