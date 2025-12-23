from abc import ABC, abstractmethod

from app.domain.enums.events import EventType
from app.services.saga.saga_step import SagaStep


class BaseSaga(ABC):
    """Base class for saga implementations.

    All saga implementations should inherit from this class and implement
    the required abstract methods to define their workflow.
    """

    @classmethod
    @abstractmethod
    def get_name(cls) -> str:
        """Get the unique name of this saga.

        Returns:
            String identifier for this saga type
        """
        pass

    @classmethod
    @abstractmethod
    def get_trigger_events(cls) -> list[EventType]:
        """Get event types that trigger this saga.

        Returns:
            List of event types that should start this saga
        """
        pass

    @abstractmethod
    def get_steps(self) -> list[SagaStep]:
        """Get saga steps in execution order.

        Returns:
            Ordered list of steps to execute for this saga
        """
        pass

    # Optional DI hook: concrete sagas may override to capture runtime deps
    def bind_dependencies(self, **_: object) -> None:
        """Inject runtime dependencies into the saga instance.

        Default implementation is a no-op; concrete sagas can override to
        accept named dependencies (e.g., producer, repositories) and store them
        for step construction. This avoids passing opaque context for DI.
        """
        return None
