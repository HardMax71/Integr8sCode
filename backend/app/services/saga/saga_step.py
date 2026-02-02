from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from fastapi.encoders import jsonable_encoder

from app.domain.events.typed import DomainEvent

T = TypeVar("T", bound=DomainEvent)


class SagaContext:
    """Context passed between saga steps"""

    def __init__(self, saga_id: str, execution_id: str):
        self.saga_id = saga_id
        self.execution_id = execution_id
        self.data: dict[str, Any] = {}
        self.compensations: list[CompensationStep] = []

    def set(self, key: str, value: Any) -> None:
        """Set context data"""
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get context data"""
        return self.data.get(key, default)

    def add_compensation(self, compensation: "CompensationStep") -> None:
        """Add compensation step"""
        self.compensations.append(compensation)

    def to_public_dict(self) -> dict[str, Any]:
        """Return a safe, persistable snapshot of context data.

        - Excludes private/ephemeral keys (prefixed with "_")
        - Encodes values to JSON-friendly types using FastAPI's jsonable_encoder
        """

        def _is_simple(val: Any) -> bool:
            if isinstance(val, (str, int, float, bool)) or val is None:
                return True
            if isinstance(val, dict):
                return all(isinstance(k, str) and _is_simple(v) for k, v in val.items())
            if isinstance(val, (list, tuple)):
                return all(_is_simple(i) for i in val)
            return False

        public: dict[str, Any] = {}
        for k, v in self.data.items():
            if isinstance(k, str) and k.startswith("_"):
                continue
            encoded = jsonable_encoder(v, exclude_none=False)
            if _is_simple(encoded):
                public[k] = encoded
            # else: drop complex/unknown types
        return public


class SagaStep(ABC, Generic[T]):
    """Base class for saga steps"""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def execute(self, context: SagaContext, event: T) -> bool:
        """
        Execute the saga step

        Returns:
            True if step succeeded and saga should continue
            False if step failed and compensation should start
        """
        pass

    @abstractmethod
    def get_compensation(self) -> "CompensationStep | None":
        """Get compensation step for this action"""
        pass

    def __str__(self) -> str:
        return f"SagaStep({self.name})"


class CompensationStep(ABC):
    """Base class for compensation steps"""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def compensate(self, context: SagaContext) -> bool:
        """
        Execute compensation logic

        Returns:
            True if compensation succeeded
            False if compensation failed
        """
        pass

    def __str__(self) -> str:
        return f"CompensationStep({self.name})"
