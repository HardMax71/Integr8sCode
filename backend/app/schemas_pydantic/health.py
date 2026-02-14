from datetime import datetime

from pydantic import BaseModel, Field


class LivenessResponse(BaseModel):
    """Response model for liveness probe."""

    status: str = Field(description="Health status")
    uptime_seconds: int = Field(description="Server uptime in seconds")
    timestamp: datetime = Field(description="Timestamp of health check")
