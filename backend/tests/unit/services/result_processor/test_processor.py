import pytest
from app.domain.enums.kafka import CONSUMER_GROUP_SUBSCRIPTIONS, GroupId, KafkaTopic
from app.services.result_processor.processor import ResultProcessorConfig

pytestmark = pytest.mark.unit


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
