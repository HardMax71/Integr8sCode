from typing import Annotated

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends
from pydantic import TypeAdapter

from app.api.dependencies import admin_user
from app.db.docs import UserDocument
from app.domain.rate_limit import RateLimitConfig, UserRateLimitUpdate
from app.schemas_pydantic.user import (
    MessageResponse,
    RateLimitRuleResponse,
    RateLimitUpdateRequest,
    RateLimitUpdateResponse,
    UserRateLimitsResponse,
)
from app.services.admin import AdminUserService

router = APIRouter(
    prefix="/admin/rate-limits",
    tags=["admin", "rate-limits"],
    route_class=DishkaRoute,
    dependencies=[Depends(admin_user)],
)

_rate_limit_update = TypeAdapter(UserRateLimitUpdate)


@router.get("/defaults", response_model=list[RateLimitRuleResponse])
async def get_default_rate_limit_rules() -> list[RateLimitRuleResponse]:
    """Get the system-level default rate limit rules applied to all users."""
    rules = RateLimitConfig.get_default_config().default_rules
    return [RateLimitRuleResponse.model_validate(r) for r in rules]


@router.get("/{user_id}", response_model=UserRateLimitsResponse)
async def get_user_rate_limits(
    admin: Annotated[UserDocument, Depends(admin_user)],
    admin_user_service: FromDishka[AdminUserService],
    user_id: str,
) -> UserRateLimitsResponse:
    """Get rate limit configuration for a user."""
    result = await admin_user_service.get_user_rate_limits(admin_user_id=admin.user_id, user_id=user_id)
    return UserRateLimitsResponse.model_validate(result)


@router.put("/{user_id}", response_model=RateLimitUpdateResponse)
async def update_user_rate_limits(
    admin: Annotated[UserDocument, Depends(admin_user)],
    admin_user_service: FromDishka[AdminUserService],
    user_id: str,
    request: RateLimitUpdateRequest,
) -> RateLimitUpdateResponse:
    """Update rate limit rules for a user."""
    update = _rate_limit_update.validate_python(request.model_dump())
    result = await admin_user_service.update_user_rate_limits(
        admin_user_id=admin.user_id, user_id=user_id, update=update
    )
    return RateLimitUpdateResponse.model_validate(result)


@router.post("/{user_id}/reset")
async def reset_user_rate_limits(
    admin: Annotated[UserDocument, Depends(admin_user)],
    admin_user_service: FromDishka[AdminUserService],
    user_id: str,
) -> MessageResponse:
    """Reset a user's rate limits to defaults."""
    await admin_user_service.reset_user_rate_limits(admin_user_id=admin.user_id, user_id=user_id)
    return MessageResponse(message=f"Rate limits reset successfully for user {user_id}")
