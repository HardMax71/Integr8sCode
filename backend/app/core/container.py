from dishka import AsyncContainer, make_async_container
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
        MessagingProvider(),
        EventProvider(),
        ConnectionProvider(),
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
        CoreServicesProvider(),
        ConnectionProvider(),
        RedisProvider(),
        EventProvider(),
        MessagingProvider(),
        ResultProcessorProvider(),
        context={Settings: settings},
    )
