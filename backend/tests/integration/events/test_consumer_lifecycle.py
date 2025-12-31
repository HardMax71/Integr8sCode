import logging
from uuid import uuid4

import pytest
from app.domain.enums.kafka import KafkaTopic
from app.events.core import ConsumerConfig, EventDispatcher, UnifiedConsumer

pytestmark = [pytest.mark.integration, pytest.mark.kafka]

_test_logger = logging.getLogger("test.events.consumer_lifecycle")


@pytest.mark.asyncio
async def test_consumer_start_status_seek_and_stop():
    cfg = ConsumerConfig(bootstrap_servers="localhost:9092", group_id=f"test-consumer-{uuid4().hex[:6]}")
    disp = EventDispatcher(logger=_test_logger)
    c = UnifiedConsumer(cfg, event_dispatcher=disp, logger=_test_logger)
    await c.start([KafkaTopic.EXECUTION_EVENTS])
    try:
        st = c.get_status()
        assert st.state == "running" and st.is_running is True
        # Exercise seek functions; don't force specific partition offsets
        await c.seek_to_beginning()
        await c.seek_to_end()
        # No need to sleep; just ensure we can call seek APIs while running
    finally:
        await c.stop()
