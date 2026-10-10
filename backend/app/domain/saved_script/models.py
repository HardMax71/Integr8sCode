from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.runtime_registry import DEFAULT_LANG, DEFAULT_LANG_VERSION


@dataclass
class DomainSavedScriptBase:
    name: str
    script: str


@dataclass
class DomainSavedScriptCreate(DomainSavedScriptBase):
    lang: str = DEFAULT_LANG
    lang_version: str = DEFAULT_LANG_VERSION
    description: str | None = None


@dataclass
class DomainSavedScript(DomainSavedScriptBase):
    script_id: str = ""
    user_id: str = ""
    lang: str = DEFAULT_LANG
    lang_version: str = DEFAULT_LANG_VERSION
    description: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DomainSavedScriptListResult:
    scripts: list[DomainSavedScript]


@dataclass
class DomainSavedScriptUpdate:
    name: str | None = None
    script: str | None = None
    lang: str | None = None
    lang_version: str | None = None
    description: str | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
