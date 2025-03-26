from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class SavedScriptBase(BaseModel):
    name: str
    script: str
    description: Optional[str] = None


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
