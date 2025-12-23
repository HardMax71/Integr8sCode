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
    timestamp: str = Field(description="ISO timestamp of health check")


class ReadinessResponse(BaseModel):
    """Response model for readiness probe."""

    status: str = Field(description="Readiness status")
    uptime_seconds: int = Field(description="Server uptime in seconds")


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    """Basic liveness probe. Does not touch external deps."""
    return LivenessResponse(
        status="ok",
        uptime_seconds=int(time.time() - _START_TIME),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness() -> ReadinessResponse:
    """Simple readiness probe. Extend with dependency checks if needed."""
    # Keep it simple and fast. Add checks (DB ping, Kafka ping) when desired.
    return ReadinessResponse(
        status="ok",
        uptime_seconds=int(time.time() - _START_TIME),
    )
