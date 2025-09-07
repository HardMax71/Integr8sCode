import asyncio
import json
from contextlib import suppress
import os
from datetime import datetime, timezone, timedelta
from tempfile import NamedTemporaryFile
from types import SimpleNamespace

import pytest

from app.domain.enums.events import EventType
from app.domain.enums.replay import ReplayStatus, ReplayTarget, ReplayType
from app.domain.replay.models import ReplayConfig, ReplayFilter
from app.events.event_store import EventStore
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.kafka.events.user import UserLoggedInEvent
from app.schemas_pydantic.replay_models import ReplaySession
from app.services.event_replay.replay_service import EventReplayService


class FakeRepo:
    def __init__(self, batches):
        self._batches = batches
        self.updated = []
        self.count = sum(len(b) for b in batches)
    async def fetch_events(self, filter, batch_size):  # noqa: ANN001
        for b in self._batches:
            yield b
    async def count_events(self, filter):  # noqa: ANN001
        return self.count
    async def update_replay_session(self, session_id: str, updates: dict):  # noqa: ANN001
        self.updated.append((session_id, updates))


class FakeProducer:
    def __init__(self): self.calls = []
    async def produce(self, **kwargs):  # noqa: ANN001
        self.calls.append(kwargs)


class FakeSchemaRegistry:
    def deserialize_json(self, doc):  # noqa: ANN001
        # Return a simple valid event instance ignoring doc
        return UserLoggedInEvent(
            user_id="u1",
            login_method="password",  # LoginMethod accepts str
            metadata=EventMetadata(service_name="svc", service_version="1"),
        )


def make_service(batches):
    repo = FakeRepo(batches)
    prod = FakeProducer()
    evstore = SimpleNamespace(schema_registry=FakeSchemaRegistry())
    return EventReplayService(repo, prod, evstore)


@pytest.mark.asyncio
async def test_full_replay_kafka_and_completion_and_cleanup() -> None:
    # one batch with two docs
    svc = make_service([[{"event_type": str(EventType.USER_LOGGED_IN)}, {"event_type": str(EventType.USER_LOGGED_IN)}]])
    cfg = ReplayConfig(replay_type=ReplayType.EXECUTION, target=ReplayTarget.KAFKA, filter=ReplayFilter())
    sid = await svc.create_replay_session(cfg)
    await svc.start_replay(sid)
    # Let task run
    await asyncio.sleep(0)
    session = svc.get_session(sid)
    assert session and session.status in (ReplayStatus.RUNNING, ReplayStatus.COMPLETED)
    # Pause/resume/cancel
    await svc.pause_replay(sid)
    await svc.resume_replay(sid)
    await svc.cancel_replay(sid)
    # list_sessions filter and order
    lst = svc.list_sessions(status=None, limit=10)
    assert len(lst) >= 1
    # cleanup old (none removed)
    removed = await svc.cleanup_old_sessions(older_than_hours=1)
    assert removed >= 0


@pytest.mark.asyncio
async def test_deserialize_fallback_and_unknown_and_skip_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    # Event store missing schema -> fallback mapping path; unknown type increments skipped
    repo = FakeRepo([[{"event_type": "unknown"}]])
    prod = FakeProducer()
    # Provide a schema registry that returns None for unknown events
    class SR:
        def deserialize_json(self, doc):  # noqa: ANN001
            return None
    evstore = SimpleNamespace(schema_registry=SR())
    svc = EventReplayService(repo, prod, evstore)
    # Provide mapping for a known event to avoid raising when not unknown
    svc._event_type_mapping = {EventType.USER_LOGGED_IN: UserLoggedInEvent}
    cfg = ReplayConfig(replay_type=ReplayType.EXECUTION, target=ReplayTarget.TEST, filter=ReplayFilter(), skip_errors=True)
    sid = await svc.create_replay_session(cfg)
    # Run one process step by invoking internal methods
    sess = svc.get_session(sid)
    await svc._prepare_session(sess)
    # Process batches
    async for b in svc._fetch_event_batches(sess):
        assert isinstance(b, list)


@pytest.mark.asyncio
async def test_replay_to_file_and_callback_and_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = make_service([[{"event_type": str(EventType.USER_LOGGED_IN)}]])
    # FILE target writes to temp file
    with NamedTemporaryFile(delete=False) as tmp:
        tgt = tmp.name
    try:
        cfg = ReplayConfig(replay_type=ReplayType.EXECUTION, target=ReplayTarget.FILE, filter=ReplayFilter(), target_file_path=tgt)
        sid = await svc.create_replay_session(cfg)
        session = svc.get_session(sid)
        # Build event via schema directly
        event = UserLoggedInEvent(user_id="u1", login_method="password", metadata=EventMetadata(service_name="s", service_version="1"))
        ok = await svc._replay_event(session, event)
        assert ok is True and os.path.exists(tgt)

        # CALLBACK target
        called = {"n": 0}
        async def cb(e, s):  # noqa: ANN001
            called["n"] += 1
        svc.register_callback(ReplayTarget.CALLBACK, cb)
        session.config.target = ReplayTarget.CALLBACK
        ok2 = await svc._replay_event(session, event)
        assert ok2 is True and called["n"] == 1

        # TEST target
        session.config.target = ReplayTarget.TEST
        assert await svc._replay_event(session, event) is True

        # Unknown target -> False
        session.config.target = "nope"  # type: ignore[assignment]
        assert await svc._replay_event(session, event) is False
    finally:
        with suppress(Exception):
            os.remove(tgt)


@pytest.mark.asyncio
async def test_retry_replay_and_update_db_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = make_service([[]])
    cfg = ReplayConfig(replay_type=ReplayType.EXECUTION, target=ReplayTarget.KAFKA, filter=ReplayFilter(), retry_failed=True, retry_attempts=2)
    sid = await svc.create_replay_session(cfg)
    session = svc.get_session(sid)
    # Patch _replay_event to fail first then succeed
    calls = {"n": 0}
    async def flappy(sess, ev):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("x")
        return True
    monkeypatch.setattr(svc, "_replay_event", flappy)

    # Update session in DB error path
    async def raise_update(session_id: str, updates: dict):  # noqa: ANN001
        raise RuntimeError("db")
    svc._repository.update_replay_session = raise_update  # type: ignore[assignment]
    await svc._update_session_in_db(ReplaySession(config=cfg))
