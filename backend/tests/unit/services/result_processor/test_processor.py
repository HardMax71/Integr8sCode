import logging

import pytest
from unittest.mock import MagicMock

from app.domain.enums.events import EventType
from app.domain.enums.kafka import GroupId, KafkaTopic
from app.services.result_processor.processor import ResultProcessor, ResultProcessorConfig


pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.result_processor.processor")


class TestResultProcessorConfig:
    def test_default_values(self):
        config = ResultProcessorConfig()
        assert config.consumer_group == GroupId.RESULT_PROCESSOR
        assert KafkaTopic.EXECUTION_COMPLETED in config.topics
        assert KafkaTopic.EXECUTION_FAILED in config.topics
        assert KafkaTopic.EXECUTION_TIMEOUT in config.topics
        assert config.result_topic == KafkaTopic.EXECUTION_RESULTS
        assert config.batch_size == 10
        assert config.processing_timeout == 300

    def test_custom_values(self):
        config = ResultProcessorConfig(batch_size=20, processing_timeout=600)
        assert config.batch_size == 20
        assert config.processing_timeout == 600


def test_create_dispatcher_registers_handlers():
    rp = ResultProcessor(execution_repo=MagicMock(), producer=MagicMock(), idempotency_manager=MagicMock(), logger=_test_logger)
    dispatcher = rp._create_dispatcher()
    assert dispatcher is not None
    assert EventType.EXECUTION_COMPLETED in dispatcher._handlers
    assert EventType.EXECUTION_FAILED in dispatcher._handlers
    assert EventType.EXECUTION_TIMEOUT in dispatcher._handlers

