from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends

from app.api.dependencies import admin_user
from app.domain.rate_limit import RateLimitConfig
from app.domain.user import User
from app.schemas_pydantic.user import RateLimitRuleResponse

router = APIRouter(
    prefix="/admin/rate-limits",
    tags=["admin", "rate-limits"],
    route_class=DishkaRoute,
    dependencies=[Depends(admin_user)],
)


@router.get("/defaults", response_model=list[RateLimitRuleResponse])
async def get_default_rate_limit_rules(
    admin: Annotated[User, Depends(admin_user)],
) -> list[RateLimitRuleResponse]:
    """Get the system-level default rate limit rules applied to all users."""
    rules = RateLimitConfig.get_default_config().default_rules
    return [RateLimitRuleResponse.model_validate(r) for r in rules]
