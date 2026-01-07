import logging
import uuid

import pytest
from app.dlq.manager import DLQManager, create_dlq_manager
from app.events.schema.schema_registry import create_schema_registry_manager

_logger = logging.getLogger("test.dlq")


@pytest.fixture
def dlq_manager(test_settings, request) -> DLQManager:
    """DLQ manager with unique consumer group per test."""
    schema_registry = create_schema_registry_manager(test_settings, _logger)
    group_suffix = f"{request.node.name[:20]}-{uuid.uuid4().hex[:8]}"
    return create_dlq_manager(
        settings=test_settings,
        schema_registry=schema_registry,
        logger=_logger,
        group_id_suffix=group_suffix,
    )
