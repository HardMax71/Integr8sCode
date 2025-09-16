from fastapi import HTTPException, Request, status

from app.core.logging import logger
from app.core.security import security_service
from app.db.repositories.user_repository import UserRepository
from app.domain.enums.user import UserRole
from app.schemas_pydantic.user import UserResponse


class AuthService:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    async def get_current_user(self, request: Request) -> UserResponse:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user = await security_service.get_current_user(token, self.user_repo)

        return UserResponse(
            user_id=user.user_id,
            username=user.username,
            email=user.email,
            role=user.role,
            is_superuser=user.is_superuser,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    async def get_admin(self, request: Request) -> UserResponse:
        user = await self.get_current_user(request)
        if user.role != UserRole.ADMIN:
            logger.warning(
                f"Admin access denied for user: {user.username} (role: {user.role})"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )
        return user
