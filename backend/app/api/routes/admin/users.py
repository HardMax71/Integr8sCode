from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError
from pydantic import TypeAdapter, ValidationError

from app.api.dependencies import admin_user
from app.db.docs import UserDocument
from app.domain.enums import UserRole
from app.domain.user import UserChanges
from app.schemas_pydantic.admin_user_overview import AdminUserOverview
from app.schemas_pydantic.common import ErrorResponse
from app.schemas_pydantic.user import (
    DeleteUserResponse,
    MessageResponse,
    PasswordResetRequest,
    UnlockResponse,
    UserCreate,
    UserListResponse,
    UserResponse,
    UserUpdate,
)
from app.services.admin import AdminUserService
from app.services.login_lockout import LoginLockoutService

router = APIRouter(
    prefix="/admin/users", tags=["admin", "users"], route_class=DishkaRoute, dependencies=[Depends(admin_user)]
)

_user_changes = TypeAdapter(UserChanges)


@router.get("/")
async def list_users(
    admin: Annotated[UserDocument, Depends(admin_user)],
    admin_user_service: FromDishka[AdminUserService],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(description="Search by username or email")] = None,
    role: Annotated[UserRole | None, Query(description="Filter by user role")] = None,
    is_active: Annotated[bool | None, Query(description="Filter by active or disabled")] = None,
    bypass_rate_limit: Annotated[bool | None, Query(description="Filter by rate limit bypass")] = None,
    has_custom_limits: Annotated[bool | None, Query(description="Filter by custom rate limits")] = None,
    custom_multiplier: Annotated[
        bool | None, Query(description="Filter by a global rate limit multiplier other than 1")
    ] = None,
) -> UserListResponse:
    """List users, filtered and paginated on the server."""
    result = await admin_user_service.list_users(
        admin_user_id=admin.user_id,
        limit=limit,
        offset=offset,
        search=search,
        role=role,
        is_active=is_active,
        bypass_rate_limit=bypass_rate_limit,
        has_custom_limits=has_custom_limits,
        custom_multiplier=custom_multiplier,
    )
    return UserListResponse.model_validate(result)


@router.post(
    "/",
    responses={409: {"model": ErrorResponse, "description": "Username already exists"}},
)
async def create_user(
    admin: Annotated[UserDocument, Depends(admin_user)],
    user_data: UserCreate,
    admin_user_service: FromDishka[AdminUserService],
) -> UserResponse:
    """Create a new user (admin only)."""
    domain_user = await admin_user_service.create_user(
        admin_user_id=admin.user_id,
        username=user_data.username,
        email=user_data.email,
        password=user_data.password,
        role=user_data.role,
        is_active=user_data.is_active,
    )
    return UserResponse.model_validate(domain_user)


@router.get(
    "/{user_id}",
    responses={404: {"model": ErrorResponse, "description": "User not found"}},
)
async def get_user(
    admin: Annotated[UserDocument, Depends(admin_user)],
    user_id: str,
    admin_user_service: FromDishka[AdminUserService],
) -> UserResponse:
    """Get a user by ID."""
    user = await admin_user_service.get_user(admin_user_id=admin.user_id, user_id=user_id)
    return UserResponse.model_validate(user)


@router.get(
    "/{user_id}/overview",
    responses={404: {"model": ErrorResponse, "description": "User not found"}},
)
async def get_user_overview(
    admin: Annotated[UserDocument, Depends(admin_user)],
    user_id: str,
    admin_user_service: FromDishka[AdminUserService],
) -> AdminUserOverview:
    """Get a comprehensive overview of a user including stats and rate limits."""
    domain = await admin_user_service.get_user_overview(user_id=user_id, hours=24)
    return AdminUserOverview.model_validate(domain)


@router.put(
    "/{user_id}",
    responses={
        404: {"model": ErrorResponse, "description": "User not found"},
        409: {"model": ErrorResponse, "description": "Username or email already exists"},
    },
)
async def update_user(
    admin: Annotated[UserDocument, Depends(admin_user)],
    user_id: str,
    user_update: UserUpdate,
    admin_user_service: FromDishka[AdminUserService],
) -> UserResponse:
    """Update a user's profile fields."""
    try:
        changes = _user_changes.validate_python(user_update.model_dump(exclude_unset=True, exclude={"password"}))
    except ValidationError as e:
        raise RequestValidationError(e.errors()) from e
    updated_user = await admin_user_service.update_user(
        admin_user_id=admin.user_id, user_id=user_id, changes=changes, password=user_update.password
    )
    return UserResponse.model_validate(updated_user)


@router.delete(
    "/{user_id}",
    responses={
        400: {"model": ErrorResponse, "description": "Cannot delete your own account"},
        404: {"model": ErrorResponse, "description": "User not found"},
    },
)
async def delete_user(
    admin: Annotated[UserDocument, Depends(admin_user)],
    user_id: str,
    admin_user_service: FromDishka[AdminUserService],
    cascade: Annotated[bool, Query(description="Cascade delete user's data")] = True,
) -> DeleteUserResponse:
    """Delete a user and optionally cascade-delete their data."""
    result = await admin_user_service.delete_user(admin_user_id=admin.user_id, user_id=user_id, cascade=cascade)
    return DeleteUserResponse.model_validate(result)


@router.post(
    "/{user_id}/reset-password",
    responses={404: {"model": ErrorResponse, "description": "User not found"}},
)
async def reset_user_password(
    admin: Annotated[UserDocument, Depends(admin_user)],
    admin_user_service: FromDishka[AdminUserService],
    user_id: str,
    password_request: PasswordResetRequest,
) -> MessageResponse:
    """Reset a user's password."""
    await admin_user_service.reset_user_password(
        admin_user_id=admin.user_id, user_id=user_id, new_password=password_request.new_password
    )
    return MessageResponse(message=f"Password reset successfully for user {user_id}")


@router.post(
    "/{user_id}/unlock",
    responses={404: {"model": ErrorResponse, "description": "User not found"}},
)
async def unlock_user(
    admin: Annotated[UserDocument, Depends(admin_user)],
    user_id: str,
    admin_user_service: FromDishka[AdminUserService],
    lockout_service: FromDishka[LoginLockoutService],
) -> UnlockResponse:
    """Unlock a user account that was locked due to failed login attempts."""
    user = await admin_user_service.get_user(admin_user_id=admin.user_id, user_id=user_id)
    await lockout_service.unlock_user(user.username)
    return UnlockResponse(user_id=user_id, message="Account unlocked")
