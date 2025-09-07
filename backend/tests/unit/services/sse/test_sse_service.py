import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.domain.enums.events import EventType
from app.infrastructure.kafka.events.system import ResultStoredEvent
from app.domain.enums.storage import StorageType
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.services.sse.sse_service import SSEService
from app.domain.enums.events import EventType


class FakeRepo:
    def __init__(self, status=None, doc=None):  # noqa: ANN001
        # Default status object with attributes
        if status is None:
            status = SimpleNamespace(
                execution_id="e1",
                status="QUEUED",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        self._status = status

        # Default execution document as attribute object
        if doc is None:
            doc = {}
        # Build minimal domain-like object with attributes used by SSEService
        def _resource_usage_obj():
            class RU:
                def to_dict(self):  # noqa: D401
                    return {}
            return RU()

        self._doc = SimpleNamespace(
            execution_id=doc.get("execution_id", "e1"),
            status=doc.get("status", "COMPLETED"),
            output=doc.get("output", ""),
            errors=doc.get("errors", None),
            lang=doc.get("lang", "python"),
            lang_version=doc.get("lang_version", "3.11"),
            resource_usage=doc.get("resource_usage", _resource_usage_obj()),
            exit_code=doc.get("exit_code", 0),
            error_type=doc.get("error_type", None),
        )

    async def get_execution_status(self, execution_id):  # noqa: ANN001
        # If test passed a dict, coerce to object with attributes
        st = self._status
        if isinstance(st, dict):
            st = SimpleNamespace(
                execution_id=execution_id,
                status=st.get("status"),
                timestamp=st.get("timestamp", datetime.now(timezone.utc).isoformat()),
            )
        return st

    async def get_execution(self, execution_id):  # noqa: ANN001
        return self._doc


class FakeBuffer:
    def __init__(self, *events):  # noqa: ANN001
        self._events = list(events)
    async def get(self, timeout=0.5):  # noqa: ANN001
        if not self._events:
            await asyncio.sleep(timeout)
            return None
        return self._events.pop(0)


class FakeSubscription:
    def __init__(self, events):  # noqa: ANN001
        self._events = list(events)
    async def get(self, timeout=0.5):  # noqa: ANN001
        import asyncio
        if not self._events:
            await asyncio.sleep(0)
            return None
        ev = self._events.pop(0)
        if ev is None:
            return None
        data = ev.model_dump(mode="json")
        return {"event_type": str(ev.event_type), "execution_id": data.get("execution_id"), "data": data}
    async def close(self):  # noqa: D401
        return None


class FakeBus:
    def __init__(self, events):  # noqa: ANN001
        self._events = list(events)
    async def open_subscription(self, execution_id):  # noqa: ANN001
        return FakeSubscription(self._events)


class FakeRouter:
    def __init__(self, buf):  # noqa: ANN001
        self._buf = buf
        self._subs = set()
    async def subscribe(self, execution_id):  # noqa: ANN001
        self._subs.add(execution_id)
        return self._buf
    async def unsubscribe(self, execution_id):  # noqa: ANN001
        self._subs.discard(execution_id)
    def get_stats(self):
        return {"num_consumers": 1, "active_executions": len(self._subs), "total_buffers": len(self._subs), "is_running": True}


class FakeShutdown:
    def __init__(self, accept=True, states=None):  # noqa: ANN001
        self._accept = accept
        self._states = states or [False]
    async def register_connection(self, execution_id, connection_id):  # noqa: ANN001
        if not self._accept:
            return None
        return asyncio.Event()
    async def unregister_connection(self, execution_id, connection_id):  # noqa: ANN001
        return None
    def is_shutting_down(self):
        # shift through states
        if self._states:
            return self._states.pop(0)
        return True
    def get_shutdown_status(self):
        return {"phase": "ready"}


def mk_result_event():
    return ResultStoredEvent(
        execution_id="e1",
        storage_type=StorageType.DATABASE,
        storage_path="/tmp/e1.json",
        size_bytes=0,
        metadata=EventMetadata(service_name="s", service_version="1"),
    )


@pytest.mark.asyncio
async def test_create_execution_stream_connected_and_terminal_event():
    ev = mk_result_event()
    repo = FakeRepo()
    router = FakeRouter(FakeBuffer())
    shutdown = FakeShutdown(accept=True)
    bus = FakeBus([ev])
    svc = SSEService(repository=repo, router=router, sse_bus=bus, shutdown_manager=shutdown, settings=SimpleNamespace(SSE_HEARTBEAT_INTERVAL=0))
    it = svc.create_execution_stream("e1", "u1")
    outs = []
    # Read until we see result_stored or a sane upper bound
    async for item in it:
        outs.append(item)
        if json_load(item).get("event_type") == str(EventType.RESULT_STORED):
            break
        if len(outs) > 10:
            break
    # Expect connected and eventually a terminal result event
    types = [json_load(o)["event_type"] for o in outs]
    assert "connected" in types and str(EventType.RESULT_STORED) in types


def json_load(o):
    import json
    return json.loads(o["data"])


@pytest.mark.asyncio
async def test_create_execution_stream_rejected_on_shutdown():
    repo = FakeRepo()
    router = FakeRouter(FakeBuffer())
    shutdown = FakeShutdown(accept=False)
    svc = SSEService(repository=repo, router=router, sse_bus=FakeBus([]), shutdown_manager=shutdown, settings=SimpleNamespace(SSE_HEARTBEAT_INTERVAL=0))
    outs = []
    async for item in svc.create_execution_stream("e1", "u1"):
        outs.append(item)
    assert json_load(outs[0])["event_type"] == "error"


@pytest.mark.asyncio
async def test_create_notification_stream_heartbeat_and_stop():
    repo = FakeRepo()
    router = FakeRouter(FakeBuffer())
    # is_shutting_down returns False once then True to stop loop
    shutdown = FakeShutdown(accept=True, states=[False, True])
    svc = SSEService(repository=repo, router=router, sse_bus=FakeBus([]), shutdown_manager=shutdown, settings=SimpleNamespace(SSE_HEARTBEAT_INTERVAL=0))
    agen = svc.create_notification_stream("u1")
    out1 = await agen.__anext__()
    assert json_load(out1)["event_type"] == "connected"
    out2 = await agen.__anext__()
    assert json_load(out2)["event_type"] == "heartbeat"


@pytest.mark.asyncio
async def test_get_health_status():
    repo = FakeRepo()
    router = FakeRouter(FakeBuffer())
    shutdown = FakeShutdown(accept=True, states=[False])
    svc = SSEService(repository=repo, router=router, sse_bus=FakeBus([]), shutdown_manager=shutdown, settings=SimpleNamespace(SSE_HEARTBEAT_INTERVAL=0))
    status = await svc.get_health_status()
    assert status.status == "healthy"
    assert status.active_consumers == 1


@pytest.mark.asyncio
async def test_event_to_sse_format_includes_result():
    repo = FakeRepo(doc={"execution_id": "e1", "status": "COMPLETED"})
    router = FakeRouter(FakeBuffer())
    shutdown = FakeShutdown(accept=True)
    svc = SSEService(repository=repo, router=router, sse_bus=FakeBus([]), shutdown_manager=shutdown, settings=SimpleNamespace(SSE_HEARTBEAT_INTERVAL=0))
    data = await svc._event_to_sse_format(mk_result_event(), "e1")
    assert data["execution_id"] == "e1"
    assert "result" in data


@pytest.mark.asyncio
async def test_event_to_sse_format_result_fallback_on_validation_error():
    # Provide doc that will fail model validation to trigger fallback
    repo = FakeRepo(doc={"execution_id": "e1", "status": object()})
    router = FakeRouter(FakeBuffer())
    shutdown = FakeShutdown(accept=True)
    svc = SSEService(repository=repo, router=router, sse_bus=FakeBus([]), shutdown_manager=shutdown, settings=SimpleNamespace(SSE_HEARTBEAT_INTERVAL=0))
    data = await svc._event_to_sse_format(mk_result_event(), "e1")
    assert data["result"]["execution_id"] == "e1"


@pytest.mark.asyncio
async def test_create_execution_stream_no_initial_status_and_multiple_events():
    # No initial status should skip that yield; then two non-terminal events; then terminal
    from app.infrastructure.kafka.events.execution import ExecutionStartedEvent
    from app.infrastructure.kafka.events.metadata import EventMetadata

    repo = FakeRepo(status=None)
    ev1 = ExecutionStartedEvent(execution_id="e1", pod_name="p1", metadata=EventMetadata(service_name="s", service_version="1"))
    ev2 = ExecutionStartedEvent(execution_id="e1", pod_name="p1", metadata=EventMetadata(service_name="s", service_version="1"))
    ev_term = mk_result_event()
    router = FakeRouter(FakeBuffer())
    shutdown = FakeShutdown(accept=True)
    bus = FakeBus([ev1, ev2, ev_term])
    svc = SSEService(repository=repo, router=router, sse_bus=bus, shutdown_manager=shutdown, settings=SimpleNamespace(SSE_HEARTBEAT_INTERVAL=0))
    outs = []
    async for item in svc.create_execution_stream("e1", "u1"):
        outs.append(json_load(item)["event_type"])
        if outs[-1] == str(EventType.RESULT_STORED):
            break
    # Should have connected first, then two execution_started, then result_stored
    assert outs[0] == "connected"
    assert outs.count(str(EventType.EXECUTION_STARTED)) == 2


@pytest.mark.asyncio
async def test_execution_stream_heartbeat_then_shutdown(monkeypatch):
    # HEARTBEAT_INTERVAL = 0 to emit immediately
    repo = FakeRepo()
    router = FakeRouter(FakeBuffer())
    shutdown_event = asyncio.Event()
    class SD(FakeShutdown):
        async def register_connection(self, execution_id, connection_id):  # noqa: ANN001
            return shutdown_event
    shutdown = SD()
    svc = SSEService(repository=repo, router=router, sse_bus=FakeBus([]), shutdown_manager=shutdown, settings=SimpleNamespace(SSE_HEARTBEAT_INTERVAL=0))
    agen = svc.create_execution_stream("e1", "u1")
    # connected
    await agen.__anext__()
    # status
    await agen.__anext__()
    # heartbeat
    hb = await agen.__anext__()
    assert json_load(hb)["event_type"] == "heartbeat"
    # trigger shutdown and expect shutdown event
    shutdown_event.set()
    sh = await agen.__anext__()
    assert json_load(sh)["event_type"] == "shutdown"
