from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


class SavedScriptBase(BaseModel):
    name: str
    script: str
    lang: str = "python"
    lang_version: str = "3.11"
    description: str | None = None

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)


class SavedScriptCreate(SavedScriptBase):
    pass


class SavedScriptUpdate(BaseModel):
    name: str | None = None
    script: str | None = None
    lang: str | None = None
    lang_version: str | None = None
    description: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)


class SavedScriptCreateRequest(SavedScriptBase):
    pass


# --8<-- [start:SavedScriptResponse]
class SavedScriptResponse(BaseModel):
    script_id: str
    name: str
    script: str
    lang: str
    lang_version: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)
# --8<-- [end:SavedScriptResponse]


class SavedScriptListResponse(BaseModel):
    scripts: list[SavedScriptResponse]

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)
