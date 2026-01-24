from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import admin_user
from app.db.repositories.admin.admin_user_repository import AdminUserRepository
from app.domain.enums.user import UserRole
from app.domain.rate_limit import RateLimitRule, UserRateLimit
from app.domain.user import UserUpdate as DomainUserUpdate
from app.schemas_pydantic.admin_user_overview import (
    AdminUserOverview,
    DerivedCounts,
    RateLimitSummary,
)
from app.schemas_pydantic.events import EventStatistics
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
    admin: Annotated[UserResponse, Depends(admin_user)],
    admin_user_service: FromDishka[AdminUserService],
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
    search: str | None = None,
    role: UserRole | None = None,
) -> UserListResponse:
    result = await admin_user_service.list_users(
        admin_username=admin.username,
        limit=limit,
        offset=offset,
        search=search,
        role=role,
    )
    return UserListResponse(
        users=[UserResponse.model_validate(u) for u in result.users],
        total=result.total,
        offset=result.offset,
        limit=result.limit,
    )


@router.post("/", response_model=UserResponse)
async def create_user(
    admin: Annotated[UserResponse, Depends(admin_user)],
    user_data: UserCreate,
    admin_user_service: FromDishka[AdminUserService],
) -> UserResponse:
    """Create a new user (admin only)."""
    # Delegate to service; map known validation error to 400
    try:
        domain_user = await admin_user_service.create_user(admin_username=admin.username, user_data=user_data)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    return UserResponse.model_validate(domain_user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    admin: Annotated[UserResponse, Depends(admin_user)],
    user_id: str,
    admin_user_service: FromDishka[AdminUserService],
) -> UserResponse:
    user = await admin_user_service.get_user(admin_username=admin.username, user_id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return UserResponse.model_validate(user)


@router.get("/{user_id}/overview", response_model=AdminUserOverview)
async def get_user_overview(
    admin: Annotated[UserResponse, Depends(admin_user)],
    user_id: str,
    admin_user_service: FromDishka[AdminUserService],
) -> AdminUserOverview:
    # Service raises ValueError if not found -> map to 404
    try:
        domain = await admin_user_service.get_user_overview(user_id=user_id, hours=24)
    except ValueError:
        raise HTTPException(status_code=404, detail="User not found")
    return AdminUserOverview(
        user=UserResponse.model_validate(domain.user),
        stats=EventStatistics.model_validate(domain.stats),
        derived_counts=DerivedCounts.model_validate(domain.derived_counts),
        rate_limit_summary=RateLimitSummary.model_validate(domain.rate_limit_summary),
        recent_events=domain.recent_events,
    )


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    admin: Annotated[UserResponse, Depends(admin_user)],
    user_id: str,
    user_update: UserUpdate,
    user_repo: FromDishka[AdminUserRepository],
    admin_user_service: FromDishka[AdminUserService],
) -> UserResponse:
    # Get existing user (explicit 404), then update
    existing_user = await user_repo.get_user_by_id(user_id)
    if not existing_user:
        raise HTTPException(status_code=404, detail="User not found")

    update_dict = user_update.model_dump(exclude_unset=True)
    domain_update = DomainUserUpdate(
        username=update_dict.get("username"),
        email=update_dict.get("email"),
        role=UserRole(update_dict["role"]) if "role" in update_dict else None,
        is_active=update_dict.get("is_active"),
        password=update_dict.get("password"),
    )

    updated_user = await admin_user_service.update_user(
        admin_username=admin.username, user_id=user_id, update=domain_update
    )
    if not updated_user:
        raise HTTPException(status_code=500, detail="Failed to update user")

    return UserResponse.model_validate(updated_user)


@router.delete("/{user_id}", response_model=DeleteUserResponse)
async def delete_user(
    admin: Annotated[UserResponse, Depends(admin_user)],
    user_id: str,
    admin_user_service: FromDishka[AdminUserService],
    cascade: bool = Query(default=True, description="Cascade delete user's data"),
) -> DeleteUserResponse:
    # Prevent self-deletion; delegate to service
    if admin.user_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    result = await admin_user_service.delete_user(
        admin_username=admin.username, user_id=user_id, cascade=cascade
    )
    return DeleteUserResponse(
        message=f"User {user_id} deleted successfully",
        user_deleted=result.user_deleted,
        executions=result.executions,
        saved_scripts=result.saved_scripts,
        notifications=result.notifications,
        user_settings=result.user_settings,
        events=result.events,
        sagas=result.sagas,
    )


@router.post("/{user_id}/reset-password", response_model=MessageResponse)
async def reset_user_password(
    admin: Annotated[UserResponse, Depends(admin_user)],
    admin_user_service: FromDishka[AdminUserService],
    user_id: str,
    password_request: PasswordResetRequest,
) -> MessageResponse:
    success = await admin_user_service.reset_user_password(
        admin_username=admin.username, user_id=user_id, new_password=password_request.new_password
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to reset password")
    return MessageResponse(message=f"Password reset successfully for user {user_id}")


@router.get("/{user_id}/rate-limits", response_model=UserRateLimitsResponse)
async def get_user_rate_limits(
    admin: Annotated[UserResponse, Depends(admin_user)],
    admin_user_service: FromDishka[AdminUserService],
    user_id: str,
) -> UserRateLimitsResponse:
    result = await admin_user_service.get_user_rate_limits(admin_username=admin.username, user_id=user_id)
    return UserRateLimitsResponse.model_validate(result)


@router.put("/{user_id}/rate-limits", response_model=RateLimitUpdateResponse)
async def update_user_rate_limits(
    admin: Annotated[UserResponse, Depends(admin_user)],
    admin_user_service: FromDishka[AdminUserService],
    user_id: str,
    request: RateLimitUpdateRequest,
) -> RateLimitUpdateResponse:
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
    admin: Annotated[UserResponse, Depends(admin_user)],
    admin_user_service: FromDishka[AdminUserService],
    user_id: str,
) -> MessageResponse:
    await admin_user_service.reset_user_rate_limits(admin_username=admin.username, user_id=user_id)
    return MessageResponse(message=f"Rate limits reset successfully for user {user_id}")
