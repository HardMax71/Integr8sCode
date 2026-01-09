import logging

import pytest
from app.events.consumer_group_monitor import ConsumerGroupHealth, NativeConsumerGroupMonitor
from app.settings import Settings

_test_logger = logging.getLogger("test.events.consumer_group_monitor")


@pytest.mark.integration
@pytest.mark.kafka
@pytest.mark.asyncio
async def test_list_groups_and_error_status(test_settings: Settings) -> None:
    mon = NativeConsumerGroupMonitor(settings=test_settings, logger=_test_logger)
    groups = await mon.list_consumer_groups()
    assert isinstance(groups, list)

    # Query a non-existent group to exercise error handling with real AdminClient
    status = await mon.get_consumer_group_status("nonexistent-group-for-tests")
    assert status.health in {ConsumerGroupHealth.UNHEALTHY, ConsumerGroupHealth.UNKNOWN}
