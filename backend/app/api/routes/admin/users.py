from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import admin_user
from app.db.repositories import AdminUserRepository
from app.domain.enums import UserRole
from app.domain.rate_limit import RateLimitRule, UserRateLimit
from app.domain.user import User
from app.domain.user import UserUpdate as DomainUserUpdate
from app.schemas_pydantic.admin_user_overview import AdminUserOverview
from app.schemas_pydantic.common import ErrorResponse
from app.schemas_pydantic.user import (
    DeleteUserResponse,
    MessageResponse,
    PasswordResetRequest,
    RateLimitUpdateRequest,
    RateLimitUpdateResponse,
    UserCreate,
    UserListResponse,
    UserRateLimitsResponse,
    UserResponse,
    UserUpdate,
)
from app.services.admin import AdminUserService

router = APIRouter(
    prefix="/admin/users", tags=["admin", "users"], route_class=DishkaRoute, dependencies=[Depends(admin_user)]
)


@router.get("/", response_model=UserListResponse)
async def list_users(
    admin: Annotated[User, Depends(admin_user)],
    admin_user_service: FromDishka[AdminUserService],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(description="Search by username or email")] = None,
    role: Annotated[UserRole | None, Query(description="Filter by user role")] = None,
) -> UserListResponse:
    """List all users with optional search and role filtering."""
    result = await admin_user_service.list_users(
        admin_username=admin.username,
        limit=limit,
        offset=offset,
        search=search,
        role=role,
    )
    return UserListResponse.model_validate(result)


@router.post(
    "/",
    response_model=UserResponse,
    responses={409: {"model": ErrorResponse, "description": "Username already exists"}},
)
async def create_user(
    admin: Annotated[User, Depends(admin_user)],
    user_data: UserCreate,
    admin_user_service: FromDishka[AdminUserService],
) -> UserResponse:
    """Create a new user (admin only)."""
    domain_user = await admin_user_service.create_user(admin_username=admin.username, user_data=user_data)
    return UserResponse.model_validate(domain_user)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    responses={404: {"model": ErrorResponse, "description": "User not found"}},
)
async def get_user(
    admin: Annotated[User, Depends(admin_user)],
    user_id: str,
    admin_user_service: FromDishka[AdminUserService],
) -> UserResponse:
    """Get a user by ID."""
    user = await admin_user_service.get_user(admin_username=admin.username, user_id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return UserResponse.model_validate(user)


@router.get(
    "/{user_id}/overview",
    response_model=AdminUserOverview,
    responses={404: {"model": ErrorResponse, "description": "User not found"}},
)
async def get_user_overview(
    admin: Annotated[User, Depends(admin_user)],
    user_id: str,
    admin_user_service: FromDishka[AdminUserService],
) -> AdminUserOverview:
    """Get a comprehensive overview of a user including stats and rate limits."""
    domain = await admin_user_service.get_user_overview(user_id=user_id, hours=24)
    return AdminUserOverview.model_validate(domain)


@router.put(
    "/{user_id}",
    response_model=UserResponse,
    responses={
        404: {"model": ErrorResponse, "description": "User not found"},
        500: {"model": ErrorResponse, "description": "Failed to update user"},
    },
)
async def update_user(
    admin: Annotated[User, Depends(admin_user)],
    user_id: str,
    user_update: UserUpdate,
    user_repo: FromDishka[AdminUserRepository],
    admin_user_service: FromDishka[AdminUserService],
) -> UserResponse:
    """Update a user's profile fields."""
    # Get existing user (explicit 404), then update
    existing_user = await user_repo.get_user_by_id(user_id)
    if not existing_user:
        raise HTTPException(status_code=404, detail="User not found")

    domain_update = DomainUserUpdate.model_validate(user_update)

    updated_user = await admin_user_service.update_user(
        admin_username=admin.username, user_id=user_id, update=domain_update
    )
    if not updated_user:
        raise HTTPException(status_code=500, detail="Failed to update user")

    return UserResponse.model_validate(updated_user)


@router.delete(
    "/{user_id}",
    response_model=DeleteUserResponse,
    responses={400: {"model": ErrorResponse, "description": "Cannot delete your own account"}},
)
async def delete_user(
    admin: Annotated[User, Depends(admin_user)],
    user_id: str,
    admin_user_service: FromDishka[AdminUserService],
    cascade: Annotated[bool, Query(description="Cascade delete user's data")] = True,
) -> DeleteUserResponse:
    """Delete a user and optionally cascade-delete their data."""
    # Prevent self-deletion; delegate to service
    if admin.user_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    result = await admin_user_service.delete_user(
        admin_username=admin.username, user_id=user_id, cascade=cascade
    )
    return DeleteUserResponse.model_validate(result)


@router.post(
    "/{user_id}/reset-password",
    response_model=MessageResponse,
    responses={500: {"model": ErrorResponse, "description": "Failed to reset password"}},
)
async def reset_user_password(
    admin: Annotated[User, Depends(admin_user)],
    admin_user_service: FromDishka[AdminUserService],
    user_id: str,
    password_request: PasswordResetRequest,
) -> MessageResponse:
    """Reset a user's password."""
    success = await admin_user_service.reset_user_password(
        admin_username=admin.username, user_id=user_id, new_password=password_request.new_password
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to reset password")
    return MessageResponse(message=f"Password reset successfully for user {user_id}")


@router.get("/{user_id}/rate-limits", response_model=UserRateLimitsResponse)
async def get_user_rate_limits(
    admin: Annotated[User, Depends(admin_user)],
    admin_user_service: FromDishka[AdminUserService],
    user_id: str,
) -> UserRateLimitsResponse:
    """Get rate limit configuration for a user."""
    result = await admin_user_service.get_user_rate_limits(admin_username=admin.username, user_id=user_id)
    return UserRateLimitsResponse.model_validate(result)


@router.put("/{user_id}/rate-limits", response_model=RateLimitUpdateResponse)
async def update_user_rate_limits(
    admin: Annotated[User, Depends(admin_user)],
    admin_user_service: FromDishka[AdminUserService],
    user_id: str,
    request: RateLimitUpdateRequest,
) -> RateLimitUpdateResponse:
    """Update rate limit rules for a user."""
    config = UserRateLimit(
        user_id=user_id,
        rules=[RateLimitRule(**r.model_dump()) for r in request.rules],
        **request.model_dump(exclude={"rules"}),
    )
    result = await admin_user_service.update_user_rate_limits(
        admin_username=admin.username, user_id=user_id, config=config
    )
    return RateLimitUpdateResponse.model_validate(result)


@router.post("/{user_id}/rate-limits/reset")
async def reset_user_rate_limits(
    admin: Annotated[User, Depends(admin_user)],
    admin_user_service: FromDishka[AdminUserService],
    user_id: str,
) -> MessageResponse:
    """Reset a user's rate limits to defaults."""
    await admin_user_service.reset_user_rate_limits(admin_username=admin.username, user_id=user_id)
    return MessageResponse(message=f"Rate limits reset successfully for user {user_id}")
