import asyncio
from types import SimpleNamespace

from app.events.admin_utils import AdminUtils


class Future:
    def __init__(self, value=None, exc: Exception | None = None):  # noqa: ANN001
        self.value = value
        self.exc = exc

    def result(self, timeout=None):  # noqa: ANN001
        if self.exc:
            raise self.exc
        return self.value


class FakeAdmin:
    def __init__(self):
        self.topics = {"t1": SimpleNamespace()}
        self.created = []

    def list_topics(self, timeout=5.0):  # noqa: ANN001
        return SimpleNamespace(topics=self.topics)

    def create_topics(self, new_topics, operation_timeout=30.0):  # noqa: ANN001
        # Record and return futures mapping by topic name
        m = {}
        for nt in new_topics:
            self.created.append(nt.topic)
            self.topics[nt.topic] = SimpleNamespace()
            m[nt.topic] = Future(None)
        return m


def test_admin_utils_topic_checks(monkeypatch):
    fake = FakeAdmin()
    monkeypatch.setattr("app.events.admin_utils.AdminClient", lambda cfg: fake)
    au = AdminUtils(bootstrap_servers="kafka:29092")
    assert au.admin_client is fake

    # Existing topic
    assert asyncio.get_event_loop().run_until_complete(au.check_topic_exists("t1")) is True
    # Create new topic via ensure
    res = asyncio.get_event_loop().run_until_complete(au.ensure_topics_exist([("t2", 1)]))
    assert res["t2"] is True
    assert "t2" in fake.topics

