import contextvars
import logging
from typing import Any, Generic, Optional, Type, TypeVar

from app.core.metrics import (
    ConnectionMetrics,
    CoordinatorMetrics,
    DatabaseMetrics,
    DLQMetrics,
    EventMetrics,
    ExecutionMetrics,
    HealthMetrics,
    KubernetesMetrics,
    NotificationMetrics,
    RateLimitMetrics,
    ReplayMetrics,
    SecurityMetrics,
)

# Type variable for generic metrics
T = TypeVar("T")


class MetricsContextVar(Generic[T]):
    """
    A wrapper around contextvars.ContextVar for type-safe metrics access.

    This class ensures that each metric type has its own context variable
    and provides a clean interface for getting and setting metrics.
    """

    def __init__(self, name: str, metric_class: Type[T], logger: logging.Logger) -> None:
        """
        Initialize a metrics context variable.

        Args:
            name: Name for the context variable (for debugging)
            metric_class: The class of the metric this context holds
            logger: Logger instance for logging
        """
        self._context_var: contextvars.ContextVar[Optional[T]] = contextvars.ContextVar(f"metrics_{name}", default=None)
        self._metric_class = metric_class
        self._name = name
        self.logger = logger

    def get(self) -> T:
        """
        Get the metric from context, creating it if necessary.

        This method implements lazy initialization - if no metric exists
        in the current context, it creates one. This is useful for testing
        and standalone scripts where the context might not be initialized.

        Returns:
            The metric instance for the current context
        """
        metric = self._context_var.get()
        if metric is None:
            # Lazy initialization with logging
            self.logger.debug(f"Lazy initializing {self._name} metrics in context")
            metric = self._metric_class()
            self._context_var.set(metric)
        return metric

    def set(self, metric: T) -> contextvars.Token[Optional[T]]:
        """
        Set the metric in the current context.

        Args:
            metric: The metric instance to set

        Returns:
            A token that can be used to reset the context
        """
        return self._context_var.set(metric)

    def reset(self) -> None:
        """Reset the metric to None in the current context."""
        self._context_var.set(None)

    def is_set(self) -> bool:
        """Check if a metric is set in the current context."""
        return self._context_var.get() is not None


# Module-level logger for lazy initialization
_module_logger: Optional[logging.Logger] = None


def _get_module_logger() -> logging.Logger:
    """Get or create module logger for lazy initialization."""
    global _module_logger
    if _module_logger is None:
        _module_logger = logging.getLogger(__name__)
    return _module_logger


# Create module-level context variables for each metric type
# These are singletons that live for the lifetime of the application
_connection_ctx = MetricsContextVar("connection", ConnectionMetrics, _get_module_logger())
_coordinator_ctx = MetricsContextVar("coordinator", CoordinatorMetrics, _get_module_logger())
_database_ctx = MetricsContextVar("database", DatabaseMetrics, _get_module_logger())
_dlq_ctx = MetricsContextVar("dlq", DLQMetrics, _get_module_logger())
_event_ctx = MetricsContextVar("event", EventMetrics, _get_module_logger())
_execution_ctx = MetricsContextVar("execution", ExecutionMetrics, _get_module_logger())
_health_ctx = MetricsContextVar("health", HealthMetrics, _get_module_logger())
_kubernetes_ctx = MetricsContextVar("kubernetes", KubernetesMetrics, _get_module_logger())
_notification_ctx = MetricsContextVar("notification", NotificationMetrics, _get_module_logger())
_rate_limit_ctx = MetricsContextVar("rate_limit", RateLimitMetrics, _get_module_logger())
_replay_ctx = MetricsContextVar("replay", ReplayMetrics, _get_module_logger())
_security_ctx = MetricsContextVar("security", SecurityMetrics, _get_module_logger())


class MetricsContext:
    """
    Central manager for all metrics contexts.

    This class provides a unified interface for managing all metric types
    in the application. It handles initialization at startup and provides
    access methods for each metric type.
    """

    @classmethod
    def initialize_all(cls, logger: logging.Logger, **metrics: Any) -> None:
        """
        Initialize all metrics contexts at application startup.

        This should be called once during application initialization,
        typically in the startup sequence after dependency injection
        has created the metric instances.

        Args:
            **metrics: Keyword arguments mapping metric names to instances
                      e.g., event=EventMetrics(), connection=ConnectionMetrics()
        """
        for name, metric_instance in metrics.items():
            if name == "connection":
                _connection_ctx.set(metric_instance)
            elif name == "coordinator":
                _coordinator_ctx.set(metric_instance)
            elif name == "database":
                _database_ctx.set(metric_instance)
            elif name == "dlq":
                _dlq_ctx.set(metric_instance)
            elif name == "event":
                _event_ctx.set(metric_instance)
            elif name == "execution":
                _execution_ctx.set(metric_instance)
            elif name == "health":
                _health_ctx.set(metric_instance)
            elif name == "kubernetes":
                _kubernetes_ctx.set(metric_instance)
            elif name == "notification":
                _notification_ctx.set(metric_instance)
            elif name == "rate_limit":
                _rate_limit_ctx.set(metric_instance)
            elif name == "replay":
                _replay_ctx.set(metric_instance)
            elif name == "security":
                _security_ctx.set(metric_instance)
            else:
                logger.warning(f"Unknown metric type: {name}")
                continue
            logger.info(f"Initialized {name} metrics in context")

    @classmethod
    def reset_all(cls, logger: logging.Logger) -> None:
        """
        Reset all metrics contexts.

        This is primarily useful for testing to ensure a clean state
        between test cases.
        """
        _connection_ctx.reset()
        _coordinator_ctx.reset()
        _database_ctx.reset()
        _dlq_ctx.reset()
        _event_ctx.reset()
        _execution_ctx.reset()
        _health_ctx.reset()
        _kubernetes_ctx.reset()
        _notification_ctx.reset()
        _rate_limit_ctx.reset()
        _replay_ctx.reset()
        _security_ctx.reset()
        logger.debug("Reset all metrics contexts")

    @classmethod
    def get_connection_metrics(cls) -> ConnectionMetrics:
        return _connection_ctx.get()

    @classmethod
    def get_coordinator_metrics(cls) -> CoordinatorMetrics:
        return _coordinator_ctx.get()

    @classmethod
    def get_database_metrics(cls) -> DatabaseMetrics:
        return _database_ctx.get()

    @classmethod
    def get_dlq_metrics(cls) -> DLQMetrics:
        return _dlq_ctx.get()

    @classmethod
    def get_event_metrics(cls) -> EventMetrics:
        return _event_ctx.get()

    @classmethod
    def get_execution_metrics(cls) -> ExecutionMetrics:
        return _execution_ctx.get()

    @classmethod
    def get_health_metrics(cls) -> HealthMetrics:
        return _health_ctx.get()

    @classmethod
    def get_kubernetes_metrics(cls) -> KubernetesMetrics:
        return _kubernetes_ctx.get()

    @classmethod
    def get_notification_metrics(cls) -> NotificationMetrics:
        return _notification_ctx.get()

    @classmethod
    def get_rate_limit_metrics(cls) -> RateLimitMetrics:
        return _rate_limit_ctx.get()

    @classmethod
    def get_replay_metrics(cls) -> ReplayMetrics:
        return _replay_ctx.get()

    @classmethod
    def get_security_metrics(cls) -> SecurityMetrics:
        return _security_ctx.get()


# Convenience functions for direct access with proper type annotations
# Import types with forward references to avoid circular imports


def get_connection_metrics() -> ConnectionMetrics:
    return MetricsContext.get_connection_metrics()


def get_coordinator_metrics() -> CoordinatorMetrics:
    return MetricsContext.get_coordinator_metrics()


def get_database_metrics() -> DatabaseMetrics:
    return MetricsContext.get_database_metrics()


def get_dlq_metrics() -> DLQMetrics:
    return MetricsContext.get_dlq_metrics()


def get_event_metrics() -> EventMetrics:
    return MetricsContext.get_event_metrics()


def get_execution_metrics() -> ExecutionMetrics:
    return MetricsContext.get_execution_metrics()


def get_health_metrics() -> HealthMetrics:
    return MetricsContext.get_health_metrics()


def get_kubernetes_metrics() -> KubernetesMetrics:
    return MetricsContext.get_kubernetes_metrics()


def get_notification_metrics() -> NotificationMetrics:
    return MetricsContext.get_notification_metrics()


def get_rate_limit_metrics() -> RateLimitMetrics:
    return MetricsContext.get_rate_limit_metrics()


def get_replay_metrics() -> ReplayMetrics:
    return MetricsContext.get_replay_metrics()


def get_security_metrics() -> SecurityMetrics:
    return MetricsContext.get_security_metrics()
