from dishka import AsyncContainer, make_async_container
from dishka.integrations.fastapi import FastapiProvider

from app.core.providers import (
    AdminServicesProvider,
    AuthProvider,
    BrokerProvider,
    BusinessServicesProvider,
    CoordinatorProvider,
    CoreServicesProvider,
    DLQWorkerProvider,
    EventReplayProvider,
    EventReplayWorkerProvider,
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


def create_app_container(settings: Settings) -> AsyncContainer:
    """Create the application DI container.

    Args:
        settings: Application settings (injected via from_context).

    Note: init_beanie() must be called BEFORE this container is created.
    KafkaBroker is created by BrokerProvider and can be retrieved
    via container.get(KafkaBroker) after container creation.
    """
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        BrokerProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        DLQWorkerProvider(),
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
        context={Settings: settings},
    )


def create_result_processor_container(settings: Settings) -> AsyncContainer:
    """Create a minimal DI container for the ResultProcessor worker."""
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        BrokerProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        ResultProcessorProvider(),
        context={Settings: settings},
    )


def create_coordinator_container(settings: Settings) -> AsyncContainer:
    """Create DI container for the ExecutionCoordinator worker."""
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        BrokerProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        CoordinatorProvider(),
        context={Settings: settings},
    )


def create_k8s_worker_container(settings: Settings) -> AsyncContainer:
    """Create DI container for the KubernetesWorker."""
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        BrokerProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        KubernetesProvider(),
        K8sWorkerProvider(),
        context={Settings: settings},
    )


def create_pod_monitor_container(settings: Settings) -> AsyncContainer:
    """Create DI container for the PodMonitor worker."""
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        BrokerProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        KafkaServicesProvider(),
        KubernetesProvider(),
        PodMonitorProvider(),
        context={Settings: settings},
    )


def create_saga_orchestrator_container(settings: Settings) -> AsyncContainer:
    """Create DI container for the SagaOrchestrator worker.

    Uses SagaWorkerProvider which adds APScheduler-managed timeout checking.
    """
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        BrokerProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        SagaWorkerProvider(),
        context={Settings: settings},
    )


def create_event_replay_container(settings: Settings) -> AsyncContainer:
    """Create DI container for the EventReplay worker.

    Uses EventReplayWorkerProvider which adds APScheduler-managed session cleanup.
    """
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        BrokerProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MetricsProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        EventReplayWorkerProvider(),
        context={Settings: settings},
    )
