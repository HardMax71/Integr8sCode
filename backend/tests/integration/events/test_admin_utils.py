import logging

import pytest
from app.events.admin_utils import AdminUtils
from app.settings import Settings

_test_logger = logging.getLogger("test.events.admin_utils")


@pytest.mark.kafka
@pytest.mark.asyncio
async def test_admin_utils_real_topic_checks(test_settings: Settings) -> None:
    topic = f"{test_settings.KAFKA_TOPIC_PREFIX}adminutils.{test_settings.KAFKA_GROUP_SUFFIX}"
    au = AdminUtils(settings=test_settings, logger=_test_logger)

    # Ensure topic exists (idempotent)
    res = await au.ensure_topics_exist([(topic, 1)])
    assert res.get(topic) in (True, False)  # Some clusters may report exists

    exists = await au.check_topic_exists(topic)
    assert exists is True
