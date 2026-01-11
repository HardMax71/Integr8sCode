from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


class DomainSavedScriptBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    script: str


class DomainSavedScriptCreate(DomainSavedScriptBase):
    lang: str = "python"
    lang_version: str = "3.11"
    description: str | None = None


class DomainSavedScript(DomainSavedScriptBase):
    script_id: str
    user_id: str
    lang: str = "python"
    lang_version: str = "3.11"
    description: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DomainSavedScriptUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str | None = None
    script: str | None = None
    lang: str | None = None
    lang_version: str | None = None
    description: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
