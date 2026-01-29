import logging
from unittest.mock import MagicMock

import pytest
from app.core.metrics import EventMetrics, ExecutionMetrics
from app.domain.enums.events import EventType
from app.domain.enums.kafka import CONSUMER_GROUP_SUBSCRIPTIONS, GroupId, KafkaTopic
from app.events.core import EventDispatcher
from app.services.result_processor.processor import ResultProcessor, ResultProcessorConfig

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.result_processor.processor")


class TestResultProcessorConfig:
    def test_default_values(self) -> None:
        config = ResultProcessorConfig()
        assert config.consumer_group == GroupId.RESULT_PROCESSOR
        # Topics should match centralized CONSUMER_GROUP_SUBSCRIPTIONS mapping
        assert set(config.topics) == CONSUMER_GROUP_SUBSCRIPTIONS[GroupId.RESULT_PROCESSOR]
        assert KafkaTopic.EXECUTION_EVENTS in config.topics
        assert config.result_topic == KafkaTopic.EXECUTION_RESULTS
        assert config.batch_size == 10
        assert config.processing_timeout == 300

    def test_custom_values(self) -> None:
        config = ResultProcessorConfig(batch_size=20, processing_timeout=600)
        assert config.batch_size == 20
        assert config.processing_timeout == 600


def test_register_handlers_populates_dispatcher(
    execution_metrics: ExecutionMetrics, event_metrics: EventMetrics
) -> None:
    dispatcher = EventDispatcher(logger=_test_logger)
    rp = ResultProcessor(
        execution_repo=MagicMock(),
        producer=MagicMock(),
        schema_registry=MagicMock(),
        settings=MagicMock(),
        dispatcher=dispatcher,
        logger=_test_logger,
        execution_metrics=execution_metrics,
        event_metrics=event_metrics,
    )
    rp._register_handlers()
    assert EventType.EXECUTION_COMPLETED in dispatcher._handlers
    assert EventType.EXECUTION_FAILED in dispatcher._handlers
    assert EventType.EXECUTION_TIMEOUT in dispatcher._handlers

