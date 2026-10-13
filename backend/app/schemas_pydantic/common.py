from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Every error the API returns: the `status` and `detail` members of RFC 9457 problem details."""

    status: int = Field(description="HTTP status code")
    detail: str = Field(description="Human-readable error message")
