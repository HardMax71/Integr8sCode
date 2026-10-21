from datetime import datetime
from typing import TypedDict

from app.domain.enums import NotificationStatus


class NotificationChanges(TypedDict, total=False):
    """Fields a delivery step sets on a notification."""

    status: NotificationStatus
    sent_at: datetime
    delivered_at: datetime
    read_at: datetime
    clicked_at: datetime
    failed_at: datetime
    retry_count: int
    error_message: str | None
