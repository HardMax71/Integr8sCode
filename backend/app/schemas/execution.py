from datetime import datetime, timezone
from typing import Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field


def generate_execution_id() -> str:
    return str(uuid4().hex)


class ExecutionBase(BaseModel):
    script: str = Field(..., max_length=50000, description="Script content (max 50,000 characters)")
    status: str = "queued"
    output: Optional[str] = None
    errors: Optional[str] = None
    lang: str = "python"
    lang_version: str = "3.11"


class ExecutionCreate(ExecutionBase):
    pass


class ExecutionInDB(ExecutionBase):
    execution_id: str = Field(default_factory=generate_execution_id, alias='id')
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resource_usage: Optional[Dict] = None

    @computed_field
    def id(self) -> str:
        return self.execution_id

    class Config:
        populate_by_name = True


class ExecutionUpdate(BaseModel):
    status: Optional[str] = None
    output: Optional[str] = None
    errors: Optional[str] = None
    resource_usage: Optional[Dict] = None


class ResourceUsage(BaseModel):
    cpu_usage: Optional[float] = Field(
        default=None, description="Current CPU usage (in cores or percentage)"
    )
    memory_usage: Optional[float] = Field(
        default=None, description="Current memory usage (in MB or GB)"
    )
    execution_time: Optional[float] = Field(
        default=None, description="Total execution time in seconds"
    )


class ExecutionRequest(BaseModel):
    script: str = Field(..., max_length=50000, description="Script content (max 50,000 characters)")
    lang: str = Field(
        default="python", description="Language name"
    )
    lang_version: str = Field(
        default="3.11", description="Language version to use for execution"
    )


class ExecutionResponse(BaseModel):
    execution_id: str
    status: str

    class Config:
        from_attributes = True


class ExecutionResult(BaseModel):
    execution_id: str
    status: str
    output: Optional[str] = None
    errors: Optional[str] = None
    lang: str
    lang_version: str
    resource_usage: Optional[ResourceUsage] = None

    class Config:
        from_attributes = True


class ResourceLimits(BaseModel):
    cpu_limit: str
    memory_limit: str
    cpu_request: str
    memory_request: str
    execution_timeout: int
    supported_runtimes: dict[str, list[str]]


class ExampleScripts(BaseModel):
    scripts: Dict[str, str]  # lang: str with script
