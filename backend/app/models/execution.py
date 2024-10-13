from datetime import datetime
from typing import Optional
from bson import ObjectId
from pydantic import BaseModel, Field


class ExecutionBase(BaseModel):
    script: str
    status: str = "queued"
    output: Optional[str] = None
    errors: Optional[str] = None
    python_version: str = "3.11"

class ExecutionCreate(ExecutionBase):
    pass

class ExecutionInDB(ExecutionBase):
    id: str = Field(default_factory=lambda: str(ObjectId()), alias='_id')
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        allow_population_by_field_name = True
        populate_by_name = True

class ExecutionUpdate(BaseModel):
    status: Optional[str] = None
    output: Optional[str] = None
    errors: Optional[str] = None