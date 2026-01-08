"""E2E tests conftest - with infrastructure cleanup and worker fixtures.

E2E tests require the full event pipeline:
- API server (started via `app` fixture from conftest.py)
- SagaOrchestrator (consumes EXECUTION_REQUESTED, publishes CreatePodCommand)
- KubernetesWorker (consumes CreatePodCommand, creates K8s pods)
- PodMonitor (watches pods, publishes ExecutionCompleted/Failed events)

The `execution_workers` fixture starts all three workers for tests that need
the full pipeline (execution to completion via SSE).
"""
import logging
from collections.abc import AsyncGenerator
from typing import Any

import pytest_asyncio
import redis.asyncio as redis
from app.core.container import (
    create_k8s_worker_container,
    create_pod_monitor_container,
    create_saga_orchestrator_container,
)
from app.core.database_context import Database
from app.db.docs import ALL_DOCUMENTS
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.k8s_worker.worker import KubernetesWorker
from app.services.pod_monitor.monitor import PodMonitor
from app.services.saga import SagaOrchestrator
from app.settings import Settings
from beanie import init_beanie

from tests.helpers.cleanup import cleanup_db_and_redis

_e2e_logger = logging.getLogger("test.e2e.workers")


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(db: Database, redis_client: redis.Redis) -> Any:
    """Clean DB and Redis before each E2E test."""
    await cleanup_db_and_redis(db, redis_client)
    yield


@pytest_asyncio.fixture(scope="module")
async def _init_schemas(test_settings: Settings) -> None:
    """Initialize event schemas once, shared across all worker fixtures."""
    container = create_saga_orchestrator_container(test_settings)
    schema_registry = await container.get(SchemaRegistryManager)
    await initialize_event_schemas(schema_registry)
    await container.close()


@pytest_asyncio.fixture(scope="module")
async def saga_orchestrator(
    test_settings: Settings, _init_schemas: None
) -> AsyncGenerator[SagaOrchestrator, None]:
    """Start SagaOrchestrator for E2E tests requiring execution pipeline."""
    container = create_saga_orchestrator_container(test_settings)

    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    orchestrator = await container.get(SagaOrchestrator)
    _e2e_logger.info("SagaOrchestrator started for E2E test")

    yield orchestrator

    await container.close()
    _e2e_logger.info("SagaOrchestrator stopped")


@pytest_asyncio.fixture(scope="module")
async def k8s_worker(
    test_settings: Settings, _init_schemas: None
) -> AsyncGenerator[KubernetesWorker, None]:
    """Start KubernetesWorker for E2E tests requiring pod creation."""
    container = create_k8s_worker_container(test_settings)

    worker = await container.get(KubernetesWorker)
    _e2e_logger.info("KubernetesWorker started for E2E test")

    if worker.v1 is None:
        await container.close()
        raise RuntimeError(
            "KubernetesWorker failed to initialize K8s client. "
            "E2E tests require a working Kubernetes cluster."
        )

    yield worker

    await container.close()
    _e2e_logger.info("KubernetesWorker stopped")


@pytest_asyncio.fixture(scope="module")
async def pod_monitor(
    test_settings: Settings, _init_schemas: None
) -> AsyncGenerator[PodMonitor, None]:
    """Start PodMonitor for E2E tests requiring pod lifecycle events."""
    container = create_pod_monitor_container(test_settings)

    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    monitor = await container.get(PodMonitor)
    _e2e_logger.info("PodMonitor started for E2E test")

    if monitor._v1 is None:  # noqa: SLF001
        await container.close()
        raise RuntimeError(
            "PodMonitor failed to initialize K8s client. "
            "E2E tests require a working Kubernetes cluster."
        )

    yield monitor

    await container.close()
    _e2e_logger.info("PodMonitor stopped")


@pytest_asyncio.fixture(scope="module")
async def execution_workers(
    saga_orchestrator: SagaOrchestrator,
    k8s_worker: KubernetesWorker,
    pod_monitor: PodMonitor,
) -> AsyncGenerator[tuple[SagaOrchestrator, KubernetesWorker, PodMonitor], None]:
    """Start all workers for tests requiring full execution pipeline.

    The complete pipeline is:
    1. API publishes ExecutionRequested
    2. SagaOrchestrator consumes it, publishes CreatePodCommand
    3. KubernetesWorker creates the pod
    4. PodMonitor watches the pod and publishes ExecutionCompleted/Failed
    5. SSE streams the terminal event to the client

    Without PodMonitor, tests hang forever waiting for terminal events.
    """
    _e2e_logger.info("All execution workers ready for E2E test")
    yield (saga_orchestrator, k8s_worker, pod_monitor)
    _e2e_logger.info("Execution workers fixture cleanup complete")
