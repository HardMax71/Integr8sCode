from fastapi import Depends, HTTPException, Request, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import Settings, get_settings
from app.core.logging import logger
from app.core.security import security_service
from app.db.mongodb import DatabaseManager
from app.db.repositories.user_repository import UserRepository, get_user_repository
from app.schemas_pydantic.user import UserResponse, UserRole


def get_settings_dependency() -> Settings:
    return get_settings()


def get_db_dependency(request: Request) -> AsyncIOMotorDatabase:
    try:
        db_manager: DatabaseManager = request.app.state.db_manager
        return db_manager.get_database()
    except AttributeError as e:
        logger.critical("DatabaseManager not found in app state. Application startup likely failed.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error: Database service not available.",
        ) from e
    except RuntimeError as e:
        logger.error(f"Error retrieving database handle: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error: Database connection issue.",
        ) from e


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
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )


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
