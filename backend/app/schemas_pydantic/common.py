from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    detail: str = Field(description="Human-readable error message")
    type: str | None = Field(default=None, description="Error type identifier")

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
