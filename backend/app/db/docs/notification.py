from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import uuid4

from beanie import Document, Indexed
from pydantic import ConfigDict, Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.domain.enums import NotificationSeverity, NotificationStatus


class NotificationDocument(Document):
    """An in-app notification: stored, then pushed to the user's open notification streams."""

    notification_id: Annotated[str, Indexed(unique=True)] = Field(default_factory=lambda: str(uuid4()))
    user_id: Annotated[str, Indexed()]
    severity: NotificationSeverity = NotificationSeverity.MEDIUM
    status: NotificationStatus = NotificationStatus.PENDING

    # Content
    subject: str
    body: str
    action_url: str = ""
    tags: list[str] = Field(default_factory=list)

    # Tracking
    created_at: Annotated[datetime, Indexed()] = Field(default_factory=lambda: datetime.now(UTC))
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    clicked_at: datetime | None = None
    failed_at: datetime | None = None

    # Error handling
    retry_count: int = 0
    max_retries: int = Field(3, ge=1)
    error_message: str | None = None

    # Context
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)

    class Settings:
        name = "notifications"
        use_state_management = True
        indexes = [
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="idx_notif_user_created_desc"),
            IndexModel([("created_at", ASCENDING)], expireAfterSeconds=30 * 86400, name="idx_notif_ttl"),
        ]
