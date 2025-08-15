from fastapi import Depends, HTTPException, Request, status

from app.core.logging import logger
from app.core.security import security_service
from app.core.service_dependencies import get_user_repository
from app.db.repositories import UserRepository
from app.schemas_pydantic.user import UserResponse, UserRole

# Database dependencies have been moved to app.core.service_dependencies
# Import them from there instead

async def get_current_user(
        request: Request,
        user_repo: UserRepository = Depends(get_user_repository),
) -> UserResponse:
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_in_db = await security_service.get_current_user(token, user_repo)

        return UserResponse(
            user_id=user_in_db.user_id,
            username=user_in_db.username,
            email=user_in_db.email,
            role=user_in_db.role,
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


async def require_admin(
        user: UserResponse = Depends(get_current_user),
) -> UserResponse:
    if user.role != UserRole.ADMIN:
        logger.warning(
            f"Admin access denied for user: {user.username} (role: {user.role})"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user
