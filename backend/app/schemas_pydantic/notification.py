from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.enums import NotificationSeverity, NotificationStatus


class NotificationResponse(BaseModel):
    """Response schema for notification endpoints"""

    notification_id: str
    status: NotificationStatus
    subject: str
    body: str
    action_url: str
    created_at: datetime
    read_at: datetime | None = None
    severity: NotificationSeverity
    tags: list[str]

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)


class NotificationListResponse(BaseModel):
    """Response schema for notification list endpoints"""

    notifications: list[NotificationResponse]
    total: int
    unread_count: int

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)


class UnreadCountResponse(BaseModel):
    """Response schema for unread notification count"""

    unread_count: int

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)


class DeleteNotificationResponse(BaseModel):
    """Response schema for notification deletion"""

    message: str

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)
