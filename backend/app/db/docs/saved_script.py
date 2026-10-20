from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from beanie import Document, Indexed
from pydantic import ConfigDict, Field

from app.runtime_registry import DEFAULT_LANG, DEFAULT_LANG_VERSION


class SavedScriptDocument(Document):
    """Saved script document as stored in database.

    Copied from SavedScriptInDB schema.
    """

    # From SavedScriptBase
    name: str
    script: str
    lang: str = DEFAULT_LANG
    lang_version: str = DEFAULT_LANG_VERSION
    description: str | None = None

    # From SavedScriptInDB
    script_id: Annotated[str, Indexed(unique=True)] = Field(default_factory=lambda: str(uuid4()))
    user_id: Annotated[str, Indexed()]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)

    class Settings:
        name = "saved_scripts"
        use_state_management = True
