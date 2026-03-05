import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from app.core.logging import setup_log_exporter, setup_logger
from app.db.docs import ALL_DOCUMENTS
from app.settings import Settings
from beanie import init_beanie
from dishka import AsyncContainer
from dishka.integrations.faststream import setup_dishka
from faststream import FastStream
from faststream.kafka import KafkaBroker
from pymongo import AsyncMongoClient


def run_worker(
    worker_name: str,
    config_override: str,
    container_factory: Callable[[Settings], AsyncContainer],
    register_handlers: Callable[[KafkaBroker], None] | None = None,
    on_startup: Callable[[AsyncContainer, KafkaBroker, structlog.stdlib.BoundLogger], Awaitable[None]] | None = None,
    on_shutdown: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Boot a worker with standardised init sequence.

    Parameters
    ----------
    worker_name:
        Human-readable name used in log messages.
    config_override:
        TOML filename passed to ``Settings(override_path=...)``.
    container_factory:
        Dishka container factory — receives ``Settings``, returns ``AsyncContainer``.
    register_handlers:
        Optional callback to register ``@broker.subscriber`` handlers **before**
        ``setup_dishka`` is called (required for subscriber auto-injection).
    on_startup:
        Optional async callback executed **after** the broker is ready.
        Receives ``(container, broker, logger)`` so it can resolve services
        and wire up APScheduler jobs, K8s setup, etc.
    on_shutdown:
        Optional async callback executed on FastStream shutdown **before**
        the container is closed.  Use for scheduler teardown etc.
    """
    settings = Settings(override_path=config_override)

    logger = setup_logger(settings.LOG_LEVEL)
    setup_log_exporter(settings, logger)

    logger.info(f"Starting {worker_name}...")

    async def _run() -> None:
        client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.MONGODB_URL, tz_aware=True)
        await init_beanie(
            database=client.get_default_database(default=settings.DATABASE_NAME),
            document_models=ALL_DOCUMENTS,
        )
        logger.info("MongoDB initialized via Beanie")

        container = container_factory(settings)

        broker: KafkaBroker = await container.get(KafkaBroker)

        if register_handlers is not None:
            register_handlers(broker)
        setup_dishka(container, broker=broker, auto_inject=True)

        startup_hooks: list[Callable[[], Awaitable[None]]] = []
        shutdown_hooks: list[Callable[[], Awaitable[None]]] = []

        if on_startup is not None:
            startup_hooks.append(lambda: on_startup(container, broker, logger))

        if on_shutdown is not None:
            shutdown_hooks.append(on_shutdown)
        shutdown_hooks.append(container.close)
        shutdown_hooks.append(client.aclose)

        app = FastStream(broker, on_startup=startup_hooks, on_shutdown=shutdown_hooks)
        await app.run()
        logger.info(f"{worker_name} shutdown complete")

    asyncio.run(_run())
