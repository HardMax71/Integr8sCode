import time
from datetime import datetime, timezone

from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/health", tags=["Health"], route_class=DishkaRoute)

_START_TIME = time.time()


class LivenessResponse(BaseModel):
    """Response model for liveness probe."""

    status: str = Field(description="Health status")
    uptime_seconds: int = Field(description="Server uptime in seconds")
    timestamp: datetime = Field(description="Timestamp of health check")


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    """Basic liveness probe. Does not touch external deps."""
    return LivenessResponse(
        status="ok",
        uptime_seconds=int(time.time() - _START_TIME),
        timestamp=datetime.now(timezone.utc),
    )
