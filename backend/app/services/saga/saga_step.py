from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from app.domain.events import DomainEvent

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
