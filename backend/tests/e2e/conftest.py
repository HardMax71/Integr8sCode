"""E2E tests conftest - with infrastructure cleanup and worker fixtures.

E2E tests require the full event pipeline:
- API server (started via `app` fixture from conftest.py)
- SagaOrchestrator (consumes EXECUTION_REQUESTED, creates pods via commands)
- KubernetesWorker (consumes CreatePodCommand, creates K8s pods, publishes completion)

The `execution_workers` fixture starts both workers as background tasks for tests
that need the full pipeline (execution to completion).
"""
import logging
from collections.abc import AsyncGenerator
from typing import Any

import pytest_asyncio
import redis.asyncio as redis
from app.core.container import create_k8s_worker_container, create_saga_orchestrator_container
from app.core.database_context import Database
from app.db.docs import ALL_DOCUMENTS
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.k8s_worker.worker import KubernetesWorker
from app.services.saga import SagaOrchestrator
from app.settings import Settings
from beanie import init_beanie

from tests.helpers.cleanup import cleanup_db_and_redis

_e2e_logger = logging.getLogger("test.e2e.workers")


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(db: Database, redis_client: redis.Redis) -> Any:
    """Clean DB and Redis before each E2E test.

    Only pre-test cleanup - post-test cleanup causes event loop issues
    when SSE/streaming tests hold connections across loop boundaries.
    """
    await cleanup_db_and_redis(db, redis_client)
    yield
    # No post-test cleanup to avoid "Event loop is closed" errors


@pytest_asyncio.fixture
async def saga_orchestrator(test_settings: Settings) -> AsyncGenerator[SagaOrchestrator, None]:
    """Start SagaOrchestrator for E2E tests requiring execution pipeline.

    The orchestrator consumes EXECUTION_REQUESTED events and creates pods.
    """
    container = create_saga_orchestrator_container(test_settings)

    # Initialize Beanie for saga persistence
    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    # Initialize schema registry
    schema_registry = await container.get(SchemaRegistryManager)
    await initialize_event_schemas(schema_registry)

    # Get and start the orchestrator
    orchestrator = await container.get(SagaOrchestrator)
    _e2e_logger.info("SagaOrchestrator started for E2E test")

    yield orchestrator

    # Container cleanup stops the orchestrator
    await container.close()
    _e2e_logger.info("SagaOrchestrator stopped")


@pytest_asyncio.fixture
async def k8s_worker(test_settings: Settings) -> AsyncGenerator[KubernetesWorker, None]:
    """Start KubernetesWorker for E2E tests requiring pod creation.

    The worker consumes CreatePodCommand events and creates actual K8s pods.
    """
    container = create_k8s_worker_container(test_settings)

    # Initialize schema registry
    schema_registry = await container.get(SchemaRegistryManager)
    await initialize_event_schemas(schema_registry)

    # Get and start the worker
    worker = await container.get(KubernetesWorker)
    _e2e_logger.info("KubernetesWorker started for E2E test")

    yield worker

    # Container cleanup stops the worker
    await container.close()
    _e2e_logger.info("KubernetesWorker stopped")


@pytest_asyncio.fixture
async def execution_workers(
    saga_orchestrator: SagaOrchestrator,
    k8s_worker: KubernetesWorker,
) -> AsyncGenerator[tuple[SagaOrchestrator, KubernetesWorker], None]:
    """Start both workers for tests requiring full execution pipeline.

    Use this fixture for tests that submit executions and wait for completion.
    The workers run as started services (not background tasks) since DI handles lifecycle.
    """
    _e2e_logger.info("Execution workers ready for E2E test")
    yield (saga_orchestrator, k8s_worker)
    _e2e_logger.info("Execution workers fixture cleanup complete")
