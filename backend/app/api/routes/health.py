import time
from datetime import datetime, timezone

from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter

from app.schemas_pydantic.health import LivenessResponse

router = APIRouter(prefix="/health", tags=["Health"], route_class=DishkaRoute)

_START_TIME = time.time()


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    """Basic liveness probe. Does not touch external deps."""
    return LivenessResponse(
        status="ok",
        uptime_seconds=int(time.time() - _START_TIME),
        timestamp=datetime.now(timezone.utc),
    )
