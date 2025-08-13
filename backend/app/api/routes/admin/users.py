from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import require_admin
from app.core.logging import logger
from app.db.repositories.admin.admin_users_repository import AdminUsersRepository, get_admin_users_repository
from app.domain.admin.user_models import (
    PasswordReset,
    UserRole,
)
from app.domain.admin.user_models import (
    UserUpdate as DomainUserUpdate,
)
from app.schemas_pydantic.user import (
    MessageResponse,
    PasswordResetRequest,
    UserListResponse,
    UserResponse,
    UserUpdate,
)

router = APIRouter(prefix="/admin/users", tags=["admin", "users"])


@router.get("/", response_model=UserListResponse)
async def list_users(
        limit: int = Query(default=100, le=1000),
        offset: int = Query(default=0, ge=0),
        search: Optional[str] = None,
        role: Optional[str] = None,
        current_user: UserResponse = Depends(require_admin),
        user_repo: AdminUsersRepository = Depends(get_admin_users_repository),
) -> UserListResponse:
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

        # Convert domain users to response models
        user_responses = [
            UserResponse(**user.to_response_dict())
            for user in result.users
        ]

        return UserListResponse(
            users=user_responses,
            total=result.total,
            offset=result.offset,
            limit=result.limit
        )

    except Exception as e:
        logger.error(f"Failed to list users: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list users")


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
        user_id: str,
        current_user: UserResponse = Depends(require_admin),
        user_repo: AdminUsersRepository = Depends(get_admin_users_repository),
) -> UserResponse:
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

        return UserResponse(**user.to_response_dict())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get user")


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
        user_id: str,
        user_update: UserUpdate,
        current_user: UserResponse = Depends(require_admin),
        user_repo: AdminUsersRepository = Depends(get_admin_users_repository),
) -> UserResponse:
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

        return UserResponse(**updated_user.to_response_dict())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update user")


@router.delete("/{user_id}", response_model=MessageResponse)
async def delete_user(
        user_id: str,
        current_user: UserResponse = Depends(require_admin),
        user_repo: AdminUsersRepository = Depends(get_admin_users_repository),
) -> MessageResponse:
    logger.info(
        "Admin deleting user",
        extra={
            "admin_username": current_user.username,
            "target_user_id": user_id,
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

        # Delete user
        success = await user_repo.delete_user(user_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete user")

        return MessageResponse(message=f"User {existing_user.username} deleted successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete user")


@router.post("/{user_id}/reset-password", response_model=MessageResponse)
async def reset_user_password(
        user_id: str,
        password_request: PasswordResetRequest,
        current_user: UserResponse = Depends(require_admin),
        user_repo: AdminUsersRepository = Depends(get_admin_users_repository),
) -> MessageResponse:
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
