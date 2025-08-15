import logging
from abc import ABC, abstractmethod
from typing import Any, Generic, Optional, TypeVar

from app.schemas_avro.event_schemas import BaseEvent

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseEvent)


class SagaContext:
    """Context passed between saga steps"""

    def __init__(self, saga_id: str, execution_id: str):
        self.saga_id = saga_id
        self.execution_id = execution_id
        self.data: dict[str, Any] = {}
        self.events: list[BaseEvent] = []
        self.compensations: list[CompensationStep] = []
        self.current_step: Optional[str] = None
        self.error: Optional[Exception] = None

    def set(self, key: str, value: Any) -> None:
        """Set context data"""
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get context data"""
        return self.data.get(key, default)

    def add_event(self, event: BaseEvent) -> None:
        """Add event to context"""
        self.events.append(event)

    def add_compensation(self, compensation: 'CompensationStep') -> None:
        """Add compensation step"""
        self.compensations.append(compensation)

    def set_error(self, error: Exception) -> None:
        """Set error in context"""
        self.error = error


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
    def get_compensation(self) -> Optional['CompensationStep']:
        """Get compensation step for this action"""
        pass

    async def can_execute(self, context: SagaContext, event: T) -> bool:
        """Check if step can be executed"""
        return True

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
