from typing import Optional

from pydantic import BaseModel


class ExecutionRequest(BaseModel):
    script: str


class ExecutionResponse(BaseModel):
    execution_id: str
    status: str


class ExecutionResult(BaseModel):
    execution_id: str
    status: str
    output: Optional[str] = None
    errors: Optional[str] = None

    class Config:
        from_attributes = True


class K8SResourceLimits(BaseModel):
    cpu_limit: str
    memory_limit: str
    cpu_request: str
    memory_request: str
