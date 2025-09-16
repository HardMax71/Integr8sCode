from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import Request

from app.schemas_pydantic.user import UserResponse
from app.services.auth_service import AuthService


@inject
async def current_user(
    request: Request,
    auth_service: FromDishka[AuthService]
) -> UserResponse:
    """Get authenticated user."""
    return await auth_service.get_current_user(request)


@inject
async def admin_user(
    request: Request,
    auth_service: FromDishka[AuthService]
) -> UserResponse:
    """Get authenticated admin user."""
    return await auth_service.get_admin(request)
