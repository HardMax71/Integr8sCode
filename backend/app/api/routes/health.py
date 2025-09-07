import time
from datetime import datetime, timezone
from typing import Any

from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["Health"], route_class=DishkaRoute)

_START_TIME = time.time()


@router.get("/live")
async def liveness() -> dict[str, Any]:
    """Basic liveness probe. Does not touch external deps."""
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - _START_TIME),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/ready")
async def readiness() -> dict[str, Any]:
    """Simple readiness probe. Extend with dependency checks if needed."""
    # Keep it simple and fast. Add checks (DB ping, Kafka ping) when desired.
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - _START_TIME),
    }
