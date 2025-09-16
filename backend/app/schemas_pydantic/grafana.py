from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class GrafanaAlertItem(BaseModel):
    status: Optional[str] = None
    labels: Dict[str, str] = Field(default_factory=dict)
    annotations: Dict[str, str] = Field(default_factory=dict)
    valueString: Optional[str] = None


class GrafanaWebhook(BaseModel):
    status: Optional[str] = None
    receiver: Optional[str] = None
    alerts: List[GrafanaAlertItem] = Field(default_factory=list)
    groupLabels: Dict[str, str] = Field(default_factory=dict)
    commonLabels: Dict[str, str] = Field(default_factory=dict)
    commonAnnotations: Dict[str, str] = Field(default_factory=dict)


class AlertResponse(BaseModel):
    message: str
    alerts_received: int
    alerts_processed: int
    errors: List[str] = Field(default_factory=list)
