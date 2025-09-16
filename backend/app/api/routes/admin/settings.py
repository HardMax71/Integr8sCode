from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from app.api.dependencies import admin_user
from app.infrastructure.mappers import SettingsMapper
from app.schemas_pydantic.admin_settings import SystemSettings
from app.schemas_pydantic.user import UserResponse
from app.services.admin import AdminSettingsService

router = APIRouter(
    prefix="/admin/settings",
    tags=["admin", "settings"],
    route_class=DishkaRoute,
    dependencies=[Depends(admin_user)]
)


@router.get("/", response_model=SystemSettings)
async def get_system_settings(
        admin: Annotated[UserResponse, Depends(admin_user)],
        service: FromDishka[AdminSettingsService],
) -> SystemSettings:
    try:
        domain_settings = await service.get_system_settings(admin.username)
        settings_mapper = SettingsMapper()
        return SystemSettings(**settings_mapper.system_settings_to_pydantic_dict(domain_settings))

    except Exception:
        raise HTTPException(status_code=500, detail="Failed to retrieve settings")


@router.put("/", response_model=SystemSettings)
async def update_system_settings(
        admin: Annotated[UserResponse, Depends(admin_user)],
        settings: SystemSettings,
        service: FromDishka[AdminSettingsService],
) -> SystemSettings:
    try:
        settings_mapper = SettingsMapper()
        domain_settings = settings_mapper.system_settings_from_pydantic(settings.model_dump())
    except (ValueError, ValidationError, KeyError) as e:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid settings: {str(e)}"
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid settings format")

    # Perform the update
    try:
        updated_domain_settings = await service.update_system_settings(
            domain_settings,
            updated_by=admin.username,
            user_id=admin.user_id,
        )

        # Convert back to pydantic schema for response
        settings_mapper = SettingsMapper()
        return SystemSettings(**settings_mapper.system_settings_to_pydantic_dict(updated_domain_settings))

    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update settings")


@router.post("/reset", response_model=SystemSettings)
async def reset_system_settings(
        admin: Annotated[UserResponse, Depends(admin_user)],
        service: FromDishka[AdminSettingsService],
) -> SystemSettings:
    try:
        reset_domain_settings = await service.reset_system_settings(admin.username, admin.user_id)
        settings_mapper = SettingsMapper()
        return SystemSettings(**settings_mapper.system_settings_to_pydantic_dict(reset_domain_settings))

    except Exception:
        raise HTTPException(status_code=500, detail="Failed to reset settings")
