from dishka import AsyncContainer, make_async_container
from dishka.integrations.fastapi import FastapiProvider

from app.core.providers import (
    AdminServicesProvider,
    AuthProvider,
    BrokerProvider,
    BusinessServicesProvider,
    CoreServicesProvider,
    DLQProvider,
    EventReplayProvider,
    ExecutionQueueProvider,
    K8sWorkerProvider,
    KafkaServicesProvider,
    KubernetesProvider,
    LoggingProvider,
    MessagingProvider,
    PodMonitorProvider,
    RedisProvider,
    RepositoryProvider,
    ResultProcessorProvider,
    RuntimeSettingsProvider,
    SagaOrchestratorProvider,
    SettingsProvider,
    SSEProvider,
    UserServicesProvider,
)
from app.settings import Settings


def create_app_container(settings: Settings) -> AsyncContainer:
    """Create the application DI container.

    Args:
        settings: Application settings (injected via from_context).

    Note: init_beanie() is called in the async lifespan AFTER this container is created.
    KafkaBroker is created by BrokerProvider and can be retrieved
    via container.get(KafkaBroker) after container creation.
    """
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        BrokerProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        DLQProvider(),
        ExecutionQueueProvider(),
        SagaOrchestratorProvider(),
        KafkaServicesProvider(),
        SSEProvider(),
        AuthProvider(),
        UserServicesProvider(),
        RuntimeSettingsProvider(),
        AdminServicesProvider(),
        EventReplayProvider(),
        BusinessServicesProvider(),
        KubernetesProvider(),
        FastapiProvider(),
        context={Settings: settings},
    )


def create_worker_container(settings: Settings) -> AsyncContainer:
    """Create the DI container for the worker process."""
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        BrokerProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        RepositoryProvider(),
        MessagingProvider(),
        DLQProvider(),
        ExecutionQueueProvider(),
        RuntimeSettingsProvider(),
        KafkaServicesProvider(),
        KubernetesProvider(),
        K8sWorkerProvider(),
        PodMonitorProvider(),
        ResultProcessorProvider(),
        SagaOrchestratorProvider(),
        context={Settings: settings},
    )
