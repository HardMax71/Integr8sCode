from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_current_user
from app.core.logging import logger
from app.db.mongodb import DatabaseManager, get_database_manager
from app.db.repositories.user_settings_repository import UserSettingsRepository
from app.schemas_pydantic.user import User
from app.schemas_pydantic.user_settings import (
    EditorSettings,
    NotificationSettings,
    RestoreSettingsRequest,
    SettingsHistoryResponse,
    ThemeUpdateRequest,
    UserSettings,
    UserSettingsUpdate,
)
from app.services.kafka_event_service import KafkaEventServiceManager
from app.services.user_settings_service import UserSettingsManager

router = APIRouter(prefix="/user/settings", tags=["user-settings"])


async def get_user_settings_repository(
        request: Request,
        db_manager: DatabaseManager = Depends(get_database_manager)
) -> UserSettingsRepository:
    """Get user settings repository.
    
    Args:
        request: FastAPI request object
        db_manager: Database manager instance
        
    Returns:
        UserSettingsRepository instance
        
    Raises:
        HTTPException: If services are not initialized
    """
    # Get settings manager
    if not hasattr(request.app.state, "settings_manager"):
        raise HTTPException(
            status_code=500,
            detail="Settings service not initialized"
        )
    settings_manager: UserSettingsManager = request.app.state.settings_manager

    # Get event service manager
    if not hasattr(request.app.state, "event_service_manager"):
        raise HTTPException(
            status_code=500,
            detail="Event service not initialized"
        )
    event_service_manager: KafkaEventServiceManager = request.app.state.event_service_manager

    # Get services
    event_service = await event_service_manager.get_service(db_manager, None)
    settings_service = await settings_manager.get_service(db_manager, event_service)

    # Create repository
    return UserSettingsRepository(db_manager, event_service, settings_service)


@router.get("/", response_model=UserSettings)
async def get_user_settings(
        current_user: User = Depends(get_current_user),
        repository: UserSettingsRepository = Depends(get_user_settings_repository)
) -> UserSettings:
    """Get user settings.
    
    Args:
        current_user: Authenticated user
        repository: User settings repository
        
    Returns:
        User settings
        
    Raises:
        HTTPException: If failed to get settings
    """
    try:
        return await repository.get_user_settings(current_user.user_id)
    except Exception as e:
        logger.error(f"Error getting user settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to get settings") from e


@router.put("/", response_model=UserSettings)
async def update_user_settings(
        updates: UserSettingsUpdate,
        current_user: User = Depends(get_current_user),
        repository: UserSettingsRepository = Depends(get_user_settings_repository)
) -> UserSettings:
    """Update user settings.
    
    Args:
        updates: Settings updates
        current_user: Authenticated user
        repository: User settings repository
        
    Returns:
        Updated user settings
        
    Raises:
        HTTPException: If failed to update settings
    """
    try:
        return await repository.update_user_settings(current_user, updates)
    except Exception as e:
        logger.error(f"Error updating user settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to update settings") from e


@router.put("/theme", response_model=UserSettings)
async def update_theme(
        request: ThemeUpdateRequest,
        current_user: User = Depends(get_current_user),
        repository: UserSettingsRepository = Depends(get_user_settings_repository)
) -> UserSettings:
    """Update user theme.
    
    Args:
        request: Theme update request
        current_user: Authenticated user
        repository: User settings repository
        
    Returns:
        Updated user settings
        
    Raises:
        HTTPException: If failed to update theme
    """
    try:
        return await repository.update_theme(current_user, request.theme)
    except Exception as e:
        logger.error(f"Error updating theme: {e}")
        raise HTTPException(status_code=500, detail="Failed to update theme") from e


@router.put("/notifications", response_model=UserSettings)
async def update_notification_settings(
        notifications: NotificationSettings,
        current_user: User = Depends(get_current_user),
        repository: UserSettingsRepository = Depends(get_user_settings_repository)
) -> UserSettings:
    """Update notification settings.
    
    Args:
        notifications: New notification settings
        current_user: Authenticated user
        repository: User settings repository
        
    Returns:
        Updated user settings
        
    Raises:
        HTTPException: If failed to update notification settings
    """
    try:
        return await repository.update_notification_settings(current_user, notifications)
    except Exception as e:
        logger.error(f"Error updating notification settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to update notifications") from e


@router.put("/editor", response_model=UserSettings)
async def update_editor_settings(
        editor: EditorSettings,
        current_user: User = Depends(get_current_user),
        repository: UserSettingsRepository = Depends(get_user_settings_repository)
) -> UserSettings:
    """Update editor settings.
    
    Args:
        editor: New editor settings
        current_user: Authenticated user
        repository: User settings repository
        
    Returns:
        Updated user settings
        
    Raises:
        HTTPException: If failed to update editor settings
    """
    try:
        return await repository.update_editor_settings(current_user, editor)
    except Exception as e:
        logger.error(f"Error updating editor settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to update editor settings") from e


@router.get("/history", response_model=SettingsHistoryResponse)
async def get_settings_history(
        limit: int = 50,
        current_user: User = Depends(get_current_user),
        repository: UserSettingsRepository = Depends(get_user_settings_repository)
) -> SettingsHistoryResponse:
    """Get settings history.
    
    Args:
        limit: Maximum number of history entries to return
        current_user: Authenticated user
        repository: User settings repository
        
    Returns:
        Settings history response
        
    Raises:
        HTTPException: If failed to get history
    """
    try:
        history = await repository.get_settings_history(current_user.user_id, limit=limit)
        return repository.format_settings_history_response(history)
    except Exception as e:
        logger.error(f"Error getting settings history: {e}")
        raise HTTPException(status_code=500, detail="Failed to get history") from e


@router.post("/restore", response_model=UserSettings)
async def restore_settings(
        request: RestoreSettingsRequest,
        current_user: User = Depends(get_current_user),
        repository: UserSettingsRepository = Depends(get_user_settings_repository)
) -> UserSettings:
    """Restore settings to a specific point in time.
    
    Args:
        request: Restore settings request
        current_user: Authenticated user
        repository: User settings repository
        
    Returns:
        Restored user settings
        
    Raises:
        HTTPException: If failed to restore settings
    """
    try:
        return await repository.restore_settings(current_user, request.timestamp)
    except Exception as e:
        logger.error(f"Error restoring settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to restore settings") from e


@router.put("/custom/{key}")
async def update_custom_setting(
        key: str,
        value: Dict[str, Any],
        current_user: User = Depends(get_current_user),
        repository: UserSettingsRepository = Depends(get_user_settings_repository)
) -> Dict[str, Any]:
    """Update a custom setting.
    
    Args:
        key: Setting key
        value: Setting value
        current_user: Authenticated user
        repository: User settings repository
        
    Returns:
        Custom setting response
        
    Raises:
        HTTPException: If failed to update custom setting
    """
    try:
        settings = await repository.update_custom_setting(current_user, key, value)
        return repository.format_custom_setting_response(key, settings)
    except Exception as e:
        logger.error(f"Error updating custom setting: {e}")
        raise HTTPException(status_code=500, detail="Failed to update custom setting") from e
