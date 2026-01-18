from dishka import AsyncContainer, make_async_container
from dishka.integrations.fastapi import FastapiProvider

from app.core.providers import (
    AdminServicesProvider,
    AuthProvider,
    BusinessServicesProvider,
    CoordinatorProvider,
    CoreServicesProvider,
    DatabaseProvider,
    DLQProcessorProvider,
    EventProvider,
    EventReplayProvider,
    K8sWorkerProvider,
    KafkaServicesProvider,
    KubernetesProvider,
    LoggingProvider,
    MessagingProvider,
    MetricsProvider,
    PodMonitorProvider,
    RedisProvider,
    RepositoryProvider,
    SagaOrchestratorProvider,
    SettingsProvider,
    SSEProvider,
    UserServicesProvider,
)
from app.settings import Settings


def create_app_container(settings: Settings) -> AsyncContainer:
    """
    Create the application DI container.

    Args:
        settings: Application settings (injected via from_context).
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
        EventProvider(),
        SagaOrchestratorProvider(),
        KafkaServicesProvider(),
        SSEProvider(),
        AuthProvider(),
        UserServicesProvider(),
        AdminServicesProvider(),
        BusinessServicesProvider(),
        FastapiProvider(),
        context={Settings: settings},
    )


def create_result_processor_container(settings: Settings) -> AsyncContainer:
    """
    Create a minimal DI container for the ResultProcessor worker.

    Args:
        settings: Application settings (injected via from_context).
    """
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        DatabaseProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        EventProvider(),
        MessagingProvider(),
        context={Settings: settings},
    )


def create_coordinator_container(settings: Settings) -> AsyncContainer:
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
        EventProvider(),
        CoordinatorProvider(),
        context={Settings: settings},
    )


def create_k8s_worker_container(settings: Settings) -> AsyncContainer:
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
        EventProvider(),
        KubernetesProvider(),
        K8sWorkerProvider(),
        context={Settings: settings},
    )


def create_pod_monitor_container(settings: Settings) -> AsyncContainer:
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
        EventProvider(),
        KafkaServicesProvider(),
        KubernetesProvider(),
        PodMonitorProvider(),
        context={Settings: settings},
    )


def create_saga_orchestrator_container(settings: Settings) -> AsyncContainer:
    """Create DI container for the SagaOrchestrator worker."""
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        DatabaseProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        EventProvider(),
        SagaOrchestratorProvider(),
        context={Settings: settings},
    )


def create_event_replay_container(settings: Settings) -> AsyncContainer:
    """Create DI container for the EventReplay worker."""
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        DatabaseProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        EventProvider(),
        EventReplayProvider(),
        context={Settings: settings},
    )


def create_dlq_processor_container(settings: Settings) -> AsyncContainer:
    """Create DI container for the DLQ processor worker."""
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        DatabaseProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        EventProvider(),
        DLQProcessorProvider(),
        context={Settings: settings},
    )
