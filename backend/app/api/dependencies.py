from typing import Optional

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import HTTPException, Request, status

from app.core.logging import logger
from app.core.security import security_service
from app.db.repositories.user_repository import UserRepository
from app.domain.enums.user import UserRole
from app.schemas_pydantic.user import User, UserResponse


class AuthService:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    async def get_current_user(self, request: Request) -> UserResponse:
        try:
            token = request.cookies.get("access_token")
            if not token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Not authenticated",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            user_in_db = await security_service.get_current_user(token, self.user_repo)

            return UserResponse(
                user_id=user_in_db.user_id,
                username=user_in_db.username,
                email=user_in_db.email,
                role=user_in_db.role,
                is_superuser=user_in_db.is_superuser,
                created_at=user_in_db.created_at,
                updated_at=user_in_db.updated_at
            )
        except Exception as e:
            logger.error(f"Authentication failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

    async def require_admin(self, request: Request) -> UserResponse:
        user = await self.get_current_user(request)
        if user.role != UserRole.ADMIN:
            logger.warning(
                f"Admin access denied for user: {user.username} (role: {user.role})"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        return user


@inject
async def require_auth_guard(
        request: Request,
        auth_service: FromDishka[AuthService],
) -> None:
    await auth_service.get_current_user(request)


@inject
async def require_admin_guard(
        request: Request,
        auth_service: FromDishka[AuthService],
) -> None:
    await auth_service.require_admin(request)


@inject
async def get_current_user_optional(
        request: Request,
        auth_service: FromDishka[AuthService],
) -> Optional[User]:
    """
    Get current user if authenticated, otherwise return None.
    This is used for optional authentication, like rate limiting.
    """
    try:
        user_response = await auth_service.get_current_user(request)
        # Convert UserResponse to User for compatibility
        return User(
            user_id=user_response.user_id,
            username=user_response.username,
            email=user_response.email,
            role=user_response.role,
            is_active=True,  # If they can authenticate, they're active
            is_superuser=user_response.is_superuser,
            created_at=user_response.created_at,
            updated_at=user_response.updated_at
        )
    except HTTPException:
        # User is not authenticated, return None
        return None
