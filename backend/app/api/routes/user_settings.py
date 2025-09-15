from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends

from app.api.dependencies import current_user
from app.infrastructure.mappers import UserSettingsApiMapper
from app.schemas_pydantic.user import UserResponse
from app.schemas_pydantic.user_settings import (
    EditorSettings,
    NotificationSettings,
    RestoreSettingsRequest,
    SettingsHistoryResponse,
    ThemeUpdateRequest,
    UserSettings,
    UserSettingsUpdate,
)
from app.services.user_settings_service import UserSettingsService

router = APIRouter(prefix="/user/settings",
                   tags=["user-settings"],
                   route_class=DishkaRoute)


@router.get("/", response_model=UserSettings)
async def get_user_settings(
        current_user: Annotated[UserResponse, Depends(current_user)],
        settings_service: FromDishka[UserSettingsService],
) -> UserSettings:
    domain = await settings_service.get_user_settings(current_user.user_id)
    return UserSettingsApiMapper.to_api_settings(domain)


@router.put("/", response_model=UserSettings)
async def update_user_settings(
        current_user: Annotated[UserResponse, Depends(current_user)],
        updates: UserSettingsUpdate,
        settings_service: FromDishka[UserSettingsService],
) -> UserSettings:
    domain_updates = UserSettingsApiMapper.to_domain_update(updates)
    domain = await settings_service.update_user_settings(current_user.user_id, domain_updates)
    return UserSettingsApiMapper.to_api_settings(domain)


@router.put("/theme", response_model=UserSettings)
async def update_theme(
        current_user: Annotated[UserResponse, Depends(current_user)],
        update_request: ThemeUpdateRequest,
        settings_service: FromDishka[UserSettingsService],
) -> UserSettings:
    domain = await settings_service.update_theme(current_user.user_id, update_request.theme)
    return UserSettingsApiMapper.to_api_settings(domain)


@router.put("/notifications", response_model=UserSettings)
async def update_notification_settings(
        current_user: Annotated[UserResponse, Depends(current_user)],
        notifications: NotificationSettings,
        settings_service: FromDishka[UserSettingsService],
) -> UserSettings:
    domain = await settings_service.update_notification_settings(
        current_user.user_id,
        UserSettingsApiMapper._to_domain_notifications(notifications),
    )
    return UserSettingsApiMapper.to_api_settings(domain)


@router.put("/editor", response_model=UserSettings)
async def update_editor_settings(
        current_user: Annotated[UserResponse, Depends(current_user)],
        editor: EditorSettings,
        settings_service: FromDishka[UserSettingsService],
) -> UserSettings:
    domain = await settings_service.update_editor_settings(
        current_user.user_id,
        UserSettingsApiMapper._to_domain_editor(editor),
    )
    return UserSettingsApiMapper.to_api_settings(domain)


@router.get("/history", response_model=SettingsHistoryResponse)
async def get_settings_history(
        current_user: Annotated[UserResponse, Depends(current_user)],
        settings_service: FromDishka[UserSettingsService],
        limit: int = 50,
) -> SettingsHistoryResponse:
    history = await settings_service.get_settings_history(current_user.user_id, limit=limit)
    return UserSettingsApiMapper.history_to_api(history)


@router.post("/restore", response_model=UserSettings)
async def restore_settings(
        current_user: Annotated[UserResponse, Depends(current_user)],
        restore_request: RestoreSettingsRequest,
        settings_service: FromDishka[UserSettingsService],
) -> UserSettings:
    domain = await settings_service.restore_settings_to_point(current_user.user_id, restore_request.timestamp)
    return UserSettingsApiMapper.to_api_settings(domain)


@router.put("/custom/{key}")
async def update_custom_setting(
        current_user: Annotated[UserResponse, Depends(current_user)],
        key: str,
        value: dict[str, object],
        settings_service: FromDishka[UserSettingsService],
) -> UserSettings:
    domain = await settings_service.update_custom_setting(current_user.user_id, key, value)
    return UserSettingsApiMapper.to_api_settings(domain)
