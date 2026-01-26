from __future__ import annotations

from pydantic import BaseModel, Field


class GrafanaAlertItem(BaseModel):
    status: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    valueString: str | None = None


class GrafanaWebhook(BaseModel):
    status: str | None = None
    receiver: str | None = None
    alerts: list[GrafanaAlertItem] = Field(default_factory=list)
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)


class AlertResponse(BaseModel):
    message: str
    alerts_received: int
    alerts_processed: int
    errors: list[str] = Field(default_factory=list)
