from datetime import datetime, timezone
from typing import List, Optional

from bson import ObjectId
from pydantic import BaseModel, Field


class SavedScriptBase(BaseModel):
    name: str
    script: str
    description: Optional[str] = None


class SavedScriptCreate(SavedScriptBase):
    pass


class SavedScriptInDB(SavedScriptBase):
    id: str = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    user_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True


class SavedScriptUpdate(BaseModel):
    name: Optional[str] = None
    script: Optional[str] = None
    description: Optional[str] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SavedScriptCreateRequest(SavedScriptBase):
    pass


class SavedScriptResponse(BaseModel):
    id: str
    name: str
    script: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SavedScriptListResponse(BaseModel):
    scripts: List[SavedScriptResponse]
