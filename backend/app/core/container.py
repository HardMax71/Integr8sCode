from dishka import AsyncContainer, make_async_container
from dishka.integrations.fastapi import FastapiProvider
from faststream.kafka import KafkaBroker

from app.core.providers import (
    AdminServicesProvider,
    AuthProvider,
    BusinessServicesProvider,
    CoordinatorProvider,
    CoreServicesProvider,
    DatabaseProvider,
    DLQProvider,
    DLQWorkerProvider,
    EventReplayProvider,
    EventReplayWorkerProvider,
    IdempotencyMiddlewareProvider,
    K8sWorkerProvider,
    KafkaServicesProvider,
    KubernetesProvider,
    LoggingProvider,
    MessagingProvider,
    MetricsProvider,
    PodMonitorProvider,
    RedisProvider,
    RepositoryProvider,
    ResourceCleanerProvider,
    ResultProcessorProvider,
    SagaOrchestratorProvider,
    SagaWorkerProvider,
    SettingsProvider,
    SSEProvider,
    UserServicesProvider,
)
from app.settings import Settings


def create_app_container(settings: Settings, broker: KafkaBroker) -> AsyncContainer:
    """
    Create the application DI container.

    Args:
        settings: Application settings (injected via from_context).
        broker: KafkaBroker instance (injected via from_context for MessagingProvider).
    """
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        DatabaseProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        DLQProvider(),
        SagaOrchestratorProvider(),
        KafkaServicesProvider(),
        SSEProvider(),
        AuthProvider(),
        UserServicesProvider(),
        AdminServicesProvider(),
        EventReplayProvider(),
        BusinessServicesProvider(),
        CoordinatorProvider(),
        KubernetesProvider(),
        ResourceCleanerProvider(),
        FastapiProvider(),
        context={Settings: settings, KafkaBroker: broker},
    )


def create_result_processor_container(settings: Settings, broker: KafkaBroker) -> AsyncContainer:
    """Create a minimal DI container for the ResultProcessor worker."""
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        DatabaseProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        IdempotencyMiddlewareProvider(),
        DLQProvider(),
        ResultProcessorProvider(),
        context={Settings: settings, KafkaBroker: broker},
    )


def create_coordinator_container(settings: Settings, broker: KafkaBroker) -> AsyncContainer:
    """Create DI container for the ExecutionCoordinator worker."""
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        DatabaseProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        IdempotencyMiddlewareProvider(),
        DLQProvider(),
        CoordinatorProvider(),
        context={Settings: settings, KafkaBroker: broker},
    )


def create_k8s_worker_container(settings: Settings, broker: KafkaBroker) -> AsyncContainer:
    """Create DI container for the KubernetesWorker."""
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        DatabaseProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        IdempotencyMiddlewareProvider(),
        DLQProvider(),
        KubernetesProvider(),
        K8sWorkerProvider(),
        context={Settings: settings, KafkaBroker: broker},
    )


def create_pod_monitor_container(settings: Settings, broker: KafkaBroker) -> AsyncContainer:
    """Create DI container for the PodMonitor worker."""
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        DatabaseProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        DLQProvider(),
        KafkaServicesProvider(),
        KubernetesProvider(),
        PodMonitorProvider(),
        context={Settings: settings, KafkaBroker: broker},
    )


def create_saga_orchestrator_container(settings: Settings, broker: KafkaBroker) -> AsyncContainer:
    """Create DI container for the SagaOrchestrator worker.

    Uses SagaWorkerProvider which adds APScheduler-managed timeout checking.
    """
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        DatabaseProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        IdempotencyMiddlewareProvider(),
        DLQProvider(),
        SagaWorkerProvider(),
        context={Settings: settings, KafkaBroker: broker},
    )


def create_event_replay_container(settings: Settings, broker: KafkaBroker) -> AsyncContainer:
    """Create DI container for the EventReplay worker.

    Uses EventReplayWorkerProvider which adds APScheduler-managed session cleanup.
    """
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        DatabaseProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        DLQProvider(),
        EventReplayWorkerProvider(),
        context={Settings: settings, KafkaBroker: broker},
    )


def create_dlq_processor_container(settings: Settings, broker: KafkaBroker) -> AsyncContainer:
    """Create DI container for the DLQ processor worker.

    Uses DLQWorkerProvider which adds APScheduler-managed retry monitoring
    and configures retry policies and filters.
    """
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        DatabaseProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        DLQWorkerProvider(),
        context={Settings: settings, KafkaBroker: broker},
    )
