import uuid
from datetime import datetime, timezone

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import AuthService, require_admin_guard
from app.core.logging import logger
from app.core.security import SecurityService
from app.core.service_dependencies import AdminUserRepositoryDep
from app.domain.admin.user_models import (
    PasswordReset,
)
from app.domain.admin.user_models import (
    UserUpdate as DomainUserUpdate,
)
from app.domain.rate_limit import UserRateLimit
from app.infrastructure.mappers.admin_mapper import UserMapper
from app.infrastructure.mappers.admin_overview_api_mapper import AdminOverviewApiMapper
from app.infrastructure.mappers.rate_limit_mapper import UserRateLimitMapper
from app.schemas_pydantic.admin_user_overview import AdminUserOverview
from app.schemas_pydantic.user import (
    MessageResponse,
    PasswordResetRequest,
    UserCreate,
    UserListResponse,
    UserResponse,
    UserRole,
    UserUpdate,
)
from app.services.admin_user_service import AdminUserService
from app.services.rate_limit_service import RateLimitService

router = APIRouter(
    prefix="/admin/users",
    tags=["admin", "users"],
    route_class=DishkaRoute,
    dependencies=[Depends(require_admin_guard)]
)


@router.get("/", response_model=UserListResponse)
async def list_users(
        request: Request,
        user_repo: AdminUserRepositoryDep,
        auth_service: FromDishka[AuthService],
        rate_limit_service: FromDishka[RateLimitService],
        limit: int = Query(default=100, le=1000),
        offset: int = Query(default=0, ge=0),
        search: str | None = None,
        role: str | None = None,
) -> UserListResponse:
    current_user = await auth_service.require_admin(request)
    logger.info(
        "Admin listing users",
        extra={
            "admin_username": current_user.username,
            "limit": limit,
            "offset": offset,
            "search": search,
            "role": role,
        },
    )

    try:
        result = await user_repo.list_users(
            limit=limit,
            offset=offset,
            search=search,
            role=role
        )

        # Convert domain users to response models with rate limit data
        user_mapper = UserMapper()
        user_responses = []
        for user in result.users:
            user_dict = user_mapper.to_response_dict(user)

            # Add rate limit summary data
            user_rate_limit = await rate_limit_service.get_user_rate_limit(user.user_id)
            if user_rate_limit:
                user_dict["bypass_rate_limit"] = user_rate_limit.bypass_rate_limit
                user_dict["global_multiplier"] = user_rate_limit.global_multiplier
                user_dict["has_custom_limits"] = bool(user_rate_limit.rules)
            else:
                user_dict["bypass_rate_limit"] = False
                user_dict["global_multiplier"] = 1.0
                user_dict["has_custom_limits"] = False

            user_responses.append(UserResponse(**user_dict))

        return UserListResponse(
            users=user_responses,
            total=result.total,
            offset=result.offset,
            limit=result.limit
        )

    except Exception as e:
        logger.error(f"Failed to list users: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list users")


@router.post("/", response_model=UserResponse)
async def create_user(
        request: Request,
        user_data: UserCreate,
        user_repo: AdminUserRepositoryDep,
        auth_service: FromDishka[AuthService],
) -> UserResponse:
    """Create a new user (admin only)."""
    current_user = await auth_service.require_admin(request)
    logger.info(
        "Admin creating new user",
        extra={
            "admin_username": current_user.username,
            "new_username": user_data.username,
        },
    )

    try:
        # Check if user already exists by searching for username
        search_result = await user_repo.list_users(
            limit=1,
            offset=0,
            search=user_data.username
        )

        # Check if exact username match exists
        for user in search_result.users:
            if user.username == user_data.username:
                raise HTTPException(
                    status_code=400,
                    detail="Username already exists"
                )

        # Hash the password
        security_service = SecurityService()
        hashed_password = security_service.get_password_hash(user_data.password)

        # Create user with proper typing
        user_id = str(uuid.uuid4())
        username = user_data.username
        email = user_data.email
        role = getattr(user_data, 'role', UserRole.USER)
        is_active = getattr(user_data, 'is_active', True)
        is_superuser = False  # Default for new users
        created_at = datetime.now(timezone.utc)
        updated_at = datetime.now(timezone.utc)
        
        # Create user document for MongoDB
        user_doc = {
            "user_id": user_id,
            "username": username,
            "email": email,
            "hashed_password": hashed_password,
            "role": role,
            "is_active": is_active,
            "is_superuser": is_superuser,
            "created_at": created_at,
            "updated_at": updated_at
        }

        # Insert directly to MongoDB
        await user_repo.users_collection.insert_one(user_doc)

        logger.info(f"User {username} created successfully by {current_user.username}")

        return UserResponse(
            user_id=user_id,
            username=username,
            email=email,
            role=role,
            is_active=is_active,
            is_superuser=is_superuser,
            created_at=created_at,
            updated_at=updated_at
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create user: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create user")


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
        user_id: str,
        user_repo: AdminUserRepositoryDep,
        request: Request,
        auth_service: FromDishka[AuthService],
) -> UserResponse:
    current_user = await auth_service.require_admin(request)
    logger.info(
        "Admin getting user details",
        extra={
            "admin_username": current_user.username,
            "target_user_id": user_id,
        },
    )

    try:
        user = await user_repo.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user_mapper = UserMapper()
        return UserResponse(**user_mapper.to_response_dict(user))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get user")


@router.get("/{user_id}/overview", response_model=AdminUserOverview)
async def get_user_overview(
        user_id: str,
        request: Request,
        auth_service: FromDishka[AuthService],
        admin_user_service: FromDishka[AdminUserService],
) -> AdminUserOverview:
    current_user = await auth_service.require_admin(request)
    logger.info(
        "Admin getting user overview",
        extra={
            "admin_username": current_user.username,
            "target_user_id": user_id,
        },
    )

    try:
        domain = await admin_user_service.get_user_overview(user_id=user_id, hours=24)
        mapper = AdminOverviewApiMapper()
        return mapper.to_response(domain)
    except ValueError:
        raise HTTPException(status_code=404, detail="User not found")
    except Exception as e:
        logger.error(f"Failed to get user overview for {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get user overview")


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
        user_id: str,
        user_update: UserUpdate,
        user_repo: AdminUserRepositoryDep,
        request: Request,
        auth_service: FromDishka[AuthService],
) -> UserResponse:
    current_user = await auth_service.require_admin(request)
    logger.info(
        "Admin updating user",
        extra={
            "admin_username": current_user.username,
            "target_user_id": user_id,
            "updates": user_update.model_dump(exclude_unset=True),
        },
    )

    try:
        # Get existing user
        existing_user = await user_repo.get_user_by_id(user_id)
        if not existing_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Convert pydantic update to domain update
        update_dict = user_update.model_dump(exclude_unset=True)
        domain_update = DomainUserUpdate(
            username=update_dict.get("username"),
            email=update_dict.get("email"),
            role=UserRole(update_dict["role"]) if "role" in update_dict else None,
            is_active=update_dict.get("is_active"),
            password=update_dict.get("password")
        )

        updated_user = await user_repo.update_user(user_id, domain_update)
        if not updated_user:
            raise HTTPException(status_code=500, detail="Failed to update user")

        user_mapper = UserMapper()
        return UserResponse(**user_mapper.to_response_dict(updated_user))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update user")


@router.delete("/{user_id}")
async def delete_user(
        user_id: str,
        user_repo: AdminUserRepositoryDep,
        request: Request,
        auth_service: FromDishka[AuthService],
        rate_limit_service: FromDishka[RateLimitService],
        cascade: bool = Query(default=True, description="Cascade delete user's data"),
) -> dict:
    current_user = await auth_service.require_admin(request)
    logger.info(
        "Admin deleting user",
        extra={
            "admin_username": current_user.username,
            "target_user_id": user_id,
            "cascade": cascade,
        },
    )

    try:
        # Prevent self-deletion
        if current_user.user_id == user_id:
            raise HTTPException(status_code=400, detail="Cannot delete your own account")

        # Get existing user
        existing_user = await user_repo.get_user_by_id(user_id)
        if not existing_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Reset rate limits for user if service available
        await rate_limit_service.reset_user_limits(user_id)

        # Delete user with cascade
        deleted_counts = await user_repo.delete_user(user_id, cascade=cascade)

        if deleted_counts.get("user", 0) == 0:
            raise HTTPException(status_code=500, detail="Failed to delete user")

        return {
            "message": f"User {existing_user.username} deleted successfully",
            "deleted_counts": deleted_counts
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete user")


@router.post("/{user_id}/reset-password", response_model=MessageResponse)
async def reset_user_password(
        user_id: str,
        password_request: PasswordResetRequest,
        request: Request,
        user_repo: AdminUserRepositoryDep,
        auth_service: FromDishka[AuthService],
) -> MessageResponse:
    current_user = await auth_service.require_admin(request)
    logger.info(
        "Admin resetting user password",
        extra={
            "admin_username": current_user.username,
            "target_user_id": user_id,
        },
    )

    try:
        # Get existing user
        existing_user = await user_repo.get_user_by_id(user_id)
        if not existing_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Create password reset domain model
        password_reset = PasswordReset(
            user_id=user_id,
            new_password=password_request.new_password
        )

        success = await user_repo.reset_user_password(password_reset)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to reset password")

        return MessageResponse(message=f"Password reset successfully for user {existing_user.username}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reset password for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reset password")


@router.get("/{user_id}/rate-limits")
async def get_user_rate_limits(
        user_id: str,
        request: Request,
        auth_service: FromDishka[AuthService],
        rate_limit_service: FromDishka[RateLimitService],
) -> dict:
    current_user = await auth_service.require_admin(request)
    logger.info(
        "Admin getting user rate limits",
        extra={
            "admin_username": current_user.username,
            "target_user_id": user_id,
        },
    )

    try:
        user_limit = await rate_limit_service.get_user_rate_limit(user_id)
        usage_stats = await rate_limit_service.get_usage_stats(user_id)
        
        rate_limit_mapper = UserRateLimitMapper()
        return {
            "user_id": user_id,
            "rate_limit_config": rate_limit_mapper.to_dict(user_limit) if user_limit else None,
            "current_usage": usage_stats
        }

    except Exception as e:
        logger.error(f"Failed to get rate limits for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get rate limits")


@router.put("/{user_id}/rate-limits")
async def update_user_rate_limits(
        user_id: str,
        rate_limit_config: UserRateLimit,
        request: Request,
        auth_service: FromDishka[AuthService],
        rate_limit_service: FromDishka[RateLimitService],
) -> dict:
    current_user = await auth_service.require_admin(request)
    rate_limit_mapper = UserRateLimitMapper()
    logger.info(
        "Admin updating user rate limits",
        extra={
            "admin_username": current_user.username,
            "target_user_id": user_id,
            "config": rate_limit_mapper.to_dict(rate_limit_config),
        },
    )

    try:
        # Ensure user_id matches
        rate_limit_config.user_id = user_id

        await rate_limit_service.update_user_rate_limit(user_id, rate_limit_config)
        
        rate_limit_mapper = UserRateLimitMapper()
        return {
            "message": "Rate limits updated successfully",
            "config": rate_limit_mapper.to_dict(rate_limit_config)
        }

    except Exception as e:
        logger.error(f"Failed to update rate limits for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update rate limits")


@router.post("/{user_id}/rate-limits/reset")
async def reset_user_rate_limits(
        user_id: str,
        request: Request,
        auth_service: FromDishka[AuthService],
        rate_limit_service: FromDishka[RateLimitService],
) -> MessageResponse:
    current_user = await auth_service.require_admin(request)
    logger.info(
        "Admin resetting user rate limits",
        extra={
            "admin_username": current_user.username,
            "target_user_id": user_id,
        },
    )

    try:
        await rate_limit_service.reset_user_limits(user_id)

        return MessageResponse(message=f"Rate limits reset successfully for user {user_id}")

    except Exception as e:
        logger.error(f"Failed to reset rate limits for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reset rate limits")
