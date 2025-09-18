import os
import uuid

import pytest

from app.events.admin_utils import AdminUtils


pytestmark = [pytest.mark.integration, pytest.mark.kafka]


def _unique_topic(prefix: str = "test") -> str:
    sid = os.environ.get("PYTEST_SESSION_ID", "sid")
    return f"{prefix}.adminutils.{sid}.{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_create_topic_and_verify_partitions() -> None:
    admin = AdminUtils()
    topic = _unique_topic()

    created = await admin.create_topic(topic, num_partitions=3, replication_factor=1)
    assert created is True

    md = admin.admin_client.list_topics(timeout=10)
    t = md.topics.get(topic)
    assert t is not None
    assert len(getattr(t, "partitions", {})) == 3


@pytest.mark.asyncio
async def test_check_topic_exists_after_ensure() -> None:
    admin = AdminUtils()
    topic = _unique_topic()

    res = await admin.ensure_topics_exist([(topic, 1)])
    assert res.get(topic) is True

    exists = await admin.check_topic_exists(topic)
    assert exists is True


@pytest.mark.asyncio
async def test_create_topic_twice_second_call_returns_false() -> None:
    admin = AdminUtils()
    topic = _unique_topic()

    first = await admin.create_topic(topic, num_partitions=1)
    second = await admin.create_topic(topic, num_partitions=1)

    assert first is True
    assert second is False

