from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Request

from app.api.dependencies import AuthService
from app.core.service_dependencies import FromDishka
from app.infrastructure.mappers.user_settings_api_mapper import UserSettingsApiMapper
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
        settings_service: FromDishka[UserSettingsService],
        request: Request,
        auth_service: FromDishka[AuthService]
) -> UserSettings:
    current_user = await auth_service.get_current_user(request)
    domain = await settings_service.get_user_settings(current_user.user_id)
    return UserSettingsApiMapper.to_api_settings(domain)


@router.put("/", response_model=UserSettings)
async def update_user_settings(
        updates: UserSettingsUpdate,
        settings_service: FromDishka[UserSettingsService],
        request: Request,
        auth_service: FromDishka[AuthService]
) -> UserSettings:
    current_user = await auth_service.get_current_user(request)
    domain_updates = UserSettingsApiMapper.to_domain_update(updates)
    domain = await settings_service.update_user_settings(current_user.user_id, domain_updates)
    return UserSettingsApiMapper.to_api_settings(domain)


@router.put("/theme", response_model=UserSettings)
async def update_theme(
        request: Request,
        update_request: ThemeUpdateRequest,
        settings_service: FromDishka[UserSettingsService],
        auth_service: FromDishka[AuthService]
) -> UserSettings:
    current_user = await auth_service.get_current_user(request)
    domain = await settings_service.update_theme(current_user.user_id, update_request.theme)
    return UserSettingsApiMapper.to_api_settings(domain)


@router.put("/notifications", response_model=UserSettings)
async def update_notification_settings(
        notifications: NotificationSettings,
        settings_service: FromDishka[UserSettingsService],
        request: Request,
        auth_service: FromDishka[AuthService]
) -> UserSettings:
    current_user = await auth_service.get_current_user(request)
    domain = await settings_service.update_notification_settings(
        current_user.user_id,
        UserSettingsApiMapper._to_domain_notifications(notifications),
    )
    return UserSettingsApiMapper.to_api_settings(domain)


@router.put("/editor", response_model=UserSettings)
async def update_editor_settings(
        editor: EditorSettings,
        settings_service: FromDishka[UserSettingsService],
        request: Request,
        auth_service: FromDishka[AuthService]
) -> UserSettings:
    current_user = await auth_service.get_current_user(request)
    domain = await settings_service.update_editor_settings(
        current_user.user_id,
        UserSettingsApiMapper._to_domain_editor(editor),
    )
    return UserSettingsApiMapper.to_api_settings(domain)


@router.get("/history", response_model=SettingsHistoryResponse)
async def get_settings_history(
        request: Request,
        settings_service: FromDishka[UserSettingsService],
        auth_service: FromDishka[AuthService],
        limit: int = 50,
) -> SettingsHistoryResponse:
    current_user = await auth_service.get_current_user(request)
    history = await settings_service.get_settings_history(current_user.user_id, limit=limit)
    return UserSettingsApiMapper.history_to_api(history)


@router.post("/restore", response_model=UserSettings)
async def restore_settings(
        request: Request,
        restore_request: RestoreSettingsRequest,
        settings_service: FromDishka[UserSettingsService],
        auth_service: FromDishka[AuthService]
) -> UserSettings:
    current_user = await auth_service.get_current_user(request)
    domain = await settings_service.restore_settings_to_point(current_user.user_id, restore_request.timestamp)
    return UserSettingsApiMapper.to_api_settings(domain)


@router.put("/custom/{key}")
async def update_custom_setting(
        key: str,
        value: dict[str, object],
        settings_service: FromDishka[UserSettingsService],
        request: Request,
        auth_service: FromDishka[AuthService]
) -> UserSettings:
    current_user = await auth_service.get_current_user(request)
    domain = await settings_service.update_custom_setting(current_user.user_id, key, value)
    return UserSettingsApiMapper.to_api_settings(domain)
