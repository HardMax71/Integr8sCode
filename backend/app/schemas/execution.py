from pydantic import BaseModel
from typing import Optional

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