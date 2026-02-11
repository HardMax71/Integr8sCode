from datetime import datetime, timezone
from uuid import uuid4

from beanie import Document, Indexed
from pydantic import ConfigDict, Field
from pymongo import ASCENDING, IndexModel

from app.domain.enums import SagaState
from app.domain.saga.models import SagaContextData


class SagaDocument(Document):
    """Domain model for saga stored in database.

    Copied from Saga/SagaInstance dataclass.
    """

    saga_id: Indexed(str, unique=True) = Field(default_factory=lambda: str(uuid4()))  # type: ignore[valid-type]
    saga_name: Indexed(str)  # type: ignore[valid-type]
    execution_id: Indexed(str)  # type: ignore[valid-type]
    state: SagaState = SagaState.CREATED  # Indexed via Settings.indexes
    current_step: str | None = None
    completed_steps: list[str] = Field(default_factory=list)
    compensated_steps: list[str] = Field(default_factory=list)
    context_data: SagaContextData = Field(default_factory=SagaContextData)
    error_message: str | None = None
    created_at: Indexed(datetime) = Field(default_factory=lambda: datetime.now(timezone.utc))  # type: ignore[valid-type]
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    retry_count: int = 0

    model_config = ConfigDict(from_attributes=True)

    class Settings:
        name = "sagas"
        use_state_management = True
        indexes = [
            IndexModel([("state", ASCENDING)], name="idx_saga_state"),
            IndexModel([("state", ASCENDING), ("created_at", ASCENDING)], name="idx_saga_state_created"),
            IndexModel(
                [("execution_id", ASCENDING), ("saga_name", ASCENDING)],
                unique=True,
                name="idx_saga_execution_name_unique",
            ),
        ]
