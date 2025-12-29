from dishka import AsyncContainer, make_async_container
from dishka.integrations.fastapi import FastapiProvider

from app.core.providers import (
    AdminServicesProvider,
    AuthProvider,
    BusinessServicesProvider,
    ConnectionProvider,
    CoreServicesProvider,
    EventProvider,
    LoggingProvider,
    MessagingProvider,
    RedisProvider,
    ResultProcessorProvider,
    SettingsProvider,
    UserServicesProvider,
)


def create_app_container() -> AsyncContainer:
    """
    Create the application DI container.
    """
    return make_async_container(
        SettingsProvider(),
        LoggingProvider(),
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
        CoreServicesProvider(),
        ConnectionProvider(),
        RedisProvider(),
        EventProvider(),
        MessagingProvider(),
        ResultProcessorProvider(),
    )
