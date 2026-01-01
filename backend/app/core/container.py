from dishka import AsyncContainer, Provider, make_async_container
from dishka.integrations.fastapi import FastapiProvider

from app.core.providers import (
    AdminServicesProvider,
    AuthProvider,
    BusinessServicesProvider,
    ConnectionProvider,
    CoreServicesProvider,
    DatabaseProvider,
    EventProvider,
    LoggingProvider,
    MessagingProvider,
    RedisProvider,
    ResultProcessorProvider,
    SettingsProvider,
    UserServicesProvider,
)


def create_app_container(settings_provider: Provider | None = None) -> AsyncContainer:
    """
    Create the application DI container.

    Args:
        settings_provider: Optional custom settings provider (e.g., for testing).
                          If None, uses the default SettingsProvider.
    """
    return make_async_container(
        settings_provider or SettingsProvider(),
        LoggingProvider(),
        DatabaseProvider(),
        RedisProvider(),
        CoreServicesProvider(),
        MessagingProvider(),
        EventProvider(),
        ConnectionProvider(),
        AuthProvider(),
        UserServicesProvider(),
        AdminServicesProvider(),
        BusinessServicesProvider(),
        FastapiProvider(),
    )


def create_result_processor_container() -> AsyncContainer:
    """
    Create a minimal DI container for the ResultProcessor worker.
    Includes only settings, database, event/kafka, and required repositories.
    """
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        DatabaseProvider(),
        CoreServicesProvider(),
        ConnectionProvider(),
        RedisProvider(),
        EventProvider(),
        MessagingProvider(),
        ResultProcessorProvider(),
    )
