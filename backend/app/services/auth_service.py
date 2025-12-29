import logging

from fastapi import Request

from app.core.security import security_service
from app.db.repositories.user_repository import UserRepository
from app.domain.enums.user import UserRole
from app.domain.user import AdminAccessRequiredError, AuthenticationRequiredError
from app.schemas_pydantic.user import UserResponse


class AuthService:
    def __init__(self, user_repo: UserRepository, logger: logging.Logger):
        self.user_repo = user_repo
        self.logger = logger

    async def get_current_user(self, request: Request) -> UserResponse:
        token = request.cookies.get("access_token")
        if not token:
            raise AuthenticationRequiredError()

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
            self.logger.warning(f"Admin access denied for user: {user.username} (role: {user.role})")
            raise AdminAccessRequiredError(user.username)
        return user
