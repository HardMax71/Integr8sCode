import logging
from unittest.mock import MagicMock

import pytest
from app.core.metrics import ExecutionMetrics
from app.domain.enums.events import EventType
from app.events.core import EventDispatcher
from app.services.result_processor.processor_logic import ProcessorLogic

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.result_processor.processor")


def test_register_handlers_registers_expected_event_types(execution_metrics: ExecutionMetrics) -> None:
    logic = ProcessorLogic(
        execution_repo=MagicMock(),
        producer=MagicMock(),
        settings=MagicMock(),
        logger=_test_logger,
        execution_metrics=execution_metrics,
    )
    dispatcher = EventDispatcher(logger=_test_logger)
    logic.register_handlers(dispatcher)

    assert EventType.EXECUTION_COMPLETED in dispatcher._handlers
    assert EventType.EXECUTION_FAILED in dispatcher._handlers
    assert EventType.EXECUTION_TIMEOUT in dispatcher._handlers
