from datetime import datetime
from typing import Optional

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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


class SavedScriptUpdate(BaseModel):
    name: Optional[str] = None
    script: Optional[str] = None
    description: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
