from datetime import datetime
from typing import Dict, List

from pydantic import BaseModel, Field

from app.domain.enums.health import AlertStatus


class Alert(BaseModel):
    status: AlertStatus
    labels: Dict[str, str]
    annotations: Dict[str, str]
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime | None = Field(alias="endsAt", default=None)
    generator_url: str = Field(alias="generatorURL")
    fingerprint: str

    class Config:
        populate_by_name = True


class AlertmanagerWebhook(BaseModel):
    version: str
    group_key: str = Field(alias="groupKey")
    truncated_alerts: int = Field(alias="truncatedAlerts", default=0)
    status: AlertStatus
    receiver: str
    group_labels: Dict[str, str] = Field(alias="groupLabels")
    common_labels: Dict[str, str] = Field(alias="commonLabels")
    common_annotations: Dict[str, str] = Field(alias="commonAnnotations")
    external_url: str = Field(alias="externalURL")
    alerts: List[Alert]

    class Config:
        populate_by_name = True


class AlertResponse(BaseModel):
    """Response after processing alerts"""
    message: str
    alerts_received: int
    alerts_processed: int
    errors: List[str] = Field(default_factory=list)
