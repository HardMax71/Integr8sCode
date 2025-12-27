import os

import pytest

from app.events.admin_utils import AdminUtils


@pytest.mark.kafka
@pytest.mark.asyncio
async def test_admin_utils_real_topic_checks() -> None:
    prefix = os.environ.get("KAFKA_TOPIC_PREFIX", "test.")
    topic = f"{prefix}adminutils.{os.environ.get('PYTEST_SESSION_ID','sid')}"
    au = AdminUtils()

    # Ensure topic exists (idempotent)
    res = await au.ensure_topics_exist([(topic, 1)])
    assert res.get(topic) in (True, False)  # Some clusters may report exists

    exists = await au.check_topic_exists(topic)
    assert exists is True
