from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from app.api.dependencies import admin_user
from app.domain.admin import (
    ExecutionLimits,
    LogLevel,
    MonitoringSettings,
    SecuritySettings,
    SystemSettings as DomainSystemSettings,
)
from app.schemas_pydantic.admin_settings import SystemSettings
from app.schemas_pydantic.user import UserResponse
from app.services.admin import AdminSettingsService


def _domain_to_pydantic(domain: DomainSystemSettings) -> SystemSettings:
    """Convert domain SystemSettings to Pydantic schema."""
    return SystemSettings.model_validate(domain, from_attributes=True)


def _pydantic_to_domain(schema: SystemSettings) -> DomainSystemSettings:
    """Convert Pydantic schema to domain SystemSettings."""
    data = schema.model_dump()
    mon = data.get("monitoring_settings", {})
    return DomainSystemSettings(
        execution_limits=ExecutionLimits(**data.get("execution_limits", {})),
        security_settings=SecuritySettings(**data.get("security_settings", {})),
        monitoring_settings=MonitoringSettings(
            metrics_retention_days=mon.get("metrics_retention_days", 30),
            log_level=LogLevel(mon.get("log_level", "INFO")),
            enable_tracing=mon.get("enable_tracing", True),
            sampling_rate=mon.get("sampling_rate", 0.1),
        ),
    )


router = APIRouter(
    prefix="/admin/settings", tags=["admin", "settings"], route_class=DishkaRoute, dependencies=[Depends(admin_user)]
)


@router.get("/", response_model=SystemSettings)
async def get_system_settings(
    admin: Annotated[UserResponse, Depends(admin_user)],
    service: FromDishka[AdminSettingsService],
) -> SystemSettings:
    try:
        domain_settings = await service.get_system_settings(admin.username)
        return _domain_to_pydantic(domain_settings)

    except Exception:
        raise HTTPException(status_code=500, detail="Failed to retrieve settings")


@router.put("/", response_model=SystemSettings)
async def update_system_settings(
    admin: Annotated[UserResponse, Depends(admin_user)],
    settings: SystemSettings,
    service: FromDishka[AdminSettingsService],
) -> SystemSettings:
    try:
        domain_settings = _pydantic_to_domain(settings)
    except (ValueError, ValidationError, KeyError) as e:
        raise HTTPException(status_code=422, detail=f"Invalid settings: {str(e)}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid settings format")

    # Perform the update
    try:
        updated_domain_settings = await service.update_system_settings(
            domain_settings,
            updated_by=admin.username,
            user_id=admin.user_id,
        )

        return _domain_to_pydantic(updated_domain_settings)

    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update settings")


@router.post("/reset", response_model=SystemSettings)
async def reset_system_settings(
    admin: Annotated[UserResponse, Depends(admin_user)],
    service: FromDishka[AdminSettingsService],
) -> SystemSettings:
    try:
        reset_domain_settings = await service.reset_system_settings(admin.username, admin.user_id)
        return _domain_to_pydantic(reset_domain_settings)

    except Exception:
        raise HTTPException(status_code=500, detail="Failed to reset settings")
