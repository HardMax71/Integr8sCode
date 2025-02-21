from typing import Optional, List

from pydantic import BaseModel, Field


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
    script: str
    python_version: Optional[str] = Field(
        default="3.11", description="Python version to use for execution"
    )


class ExecutionResponse(BaseModel):
    execution_id: str
    status: str


class ExecutionResult(BaseModel):
    execution_id: str
    status: str
    output: Optional[str] = None
    errors: Optional[str] = None
    python_version: str
    resource_usage: Optional[ResourceUsage] = None

    class Config:
        from_attributes = True


class K8SResourceLimits(BaseModel):
    cpu_limit: str
    memory_limit: str
    cpu_request: str
    memory_request: str
    execution_timeout: int
    supported_python_versions: List[str]
