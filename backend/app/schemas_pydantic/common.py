from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    detail: str = Field(description="Human-readable error message")
    type: str | None = Field(default=None, description="Error type identifier")
