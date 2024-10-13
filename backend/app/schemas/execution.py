from typing import Optional, List
from pydantic import BaseModel, Field

class ExecutionRequest(BaseModel):
    script: str
    python_version: Optional[str] = Field(default="3.11", description="Python version to use for execution")

class ExecutionResponse(BaseModel):
    execution_id: str
    status: str


class ExecutionResult(BaseModel):
    execution_id: str
    status: str
    output: Optional[str] = None
    errors: Optional[str] = None
    python_version: str

    class Config:
        from_attributes = True

class K8SResourceLimits(BaseModel):
    cpu_limit: str
    memory_limit: str
    cpu_request: str
    memory_request: str
    execution_timeout: int
    supported_python_versions: List[str]