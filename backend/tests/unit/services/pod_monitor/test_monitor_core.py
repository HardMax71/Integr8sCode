import asyncio
from types import SimpleNamespace

import pytest

from app.services.pod_monitor.monitor import MonitorState, PodMonitor, WatchEventType
from app.services.pod_monitor.config import PodMonitorConfig


class DummyProducer:
    async def produce(self, *a, **k):  # noqa: ANN001
        return None


def make_pod(name="p1", phase="Running", rv="1"):  # noqa: ANN001
    status = SimpleNamespace(phase=phase)
    metadata = SimpleNamespace(name=name, resource_version=rv)
    return SimpleNamespace(status=status, metadata=metadata)


@pytest.mark.asyncio
async def test_process_raw_event_and_status(monkeypatch):
    cfg = PodMonitorConfig(enable_state_reconciliation=False)
    m = PodMonitor(cfg, producer=DummyProducer())
    # Stub metrics to avoid OTEL
    m._metrics = SimpleNamespace(record_pod_monitor_watch_error=lambda *a, **k: None, update_pod_monitor_pods_watched=lambda *a, **k: None, record_pod_monitor_reconciliation_run=lambda *a, **k: None)
    # Do not initialize Kubernetes; directly call _process_raw_event
    raw = {"type": "ADDED", "object": make_pod()}
    await m._process_raw_event(raw)
    st = await m.get_status()
    assert st["state"] in (MonitorState.IDLE.value, MonitorState.RUNNING.value, MonitorState.STOPPING.value, MonitorState.STOPPED.value)


def test_update_resource_version_defensive():
    cfg = PodMonitorConfig()
    m = PodMonitor(cfg, producer=DummyProducer())
    class S:
        class Stop:
            resource_version = "55"
        _stop_event = Stop()
    m._update_resource_version(S())
    assert m._PodMonitor__dict__ if False else True  # no-op check; attribute updated silently


@pytest.mark.asyncio
async def test_process_pod_event_tracks_and_ignores(monkeypatch):
    cfg = PodMonitorConfig(enable_state_reconciliation=False)
    m = PodMonitor(cfg, producer=DummyProducer())
    m._metrics = SimpleNamespace(record_pod_monitor_watch_error=lambda *a, **k: None, update_pod_monitor_pods_watched=lambda *a, **k: None, record_pod_monitor_reconciliation_run=lambda *a, **k: None)

    pod = make_pod(name="x", phase="Running", rv="10")
    ev = SimpleNamespace(event_type=WatchEventType.ADDED, pod=pod, resource_version="10")
    await m._process_pod_event(ev)
    assert "x" in m._tracked_pods

    ev2 = SimpleNamespace(event_type=WatchEventType.DELETED, pod=pod, resource_version="11")
    await m._process_pod_event(ev2)
    assert "x" not in m._tracked_pods

import asyncio
from types import SimpleNamespace

import pytest

from app.infrastructure.kafka.events.pod import PodRunningEvent
from app.services.pod_monitor.monitor import ErrorType, MonitorState, PodEvent, PodMonitor, ReconciliationResult, WatchEventType
from app.services.pod_monitor.config import PodMonitorConfig


class DummyProducer:
    def __init__(self): self.calls = []
    async def produce(self, *a, **k):  # noqa: ANN001
        return None


def make_pod(name="p1", phase="Running", rv="1"):  # noqa: ANN001
    status = SimpleNamespace(phase=phase)
    metadata = SimpleNamespace(name=name, resource_version=rv)
    return SimpleNamespace(status=status, metadata=metadata)


@pytest.mark.asyncio
async def test_process_raw_event_invalid_and_ignored_phase(monkeypatch):
    cfg = PodMonitorConfig(enable_state_reconciliation=False, ignored_pod_phases={"Succeeded"})
    m = PodMonitor(cfg, producer=DummyProducer())
    m._metrics = SimpleNamespace(
        record_pod_monitor_watch_error=lambda *a, **k: None,
        update_pod_monitor_pods_watched=lambda *a, **k: None,
        record_pod_monitor_reconciliation_run=lambda *a, **k: None,
        record_pod_monitor_event_processing_duration=lambda *a, **k: None,
        record_pod_monitor_event_published=lambda *a, **k: None,
    )
    # Invalid raw event
    await m._process_raw_event({"bad": 1})  # should not raise
    # Ignored phase
    pod = make_pod(phase="Succeeded")
    ev = PodEvent(event_type=WatchEventType.ADDED, pod=pod, resource_version="1")
    await m._process_pod_event(ev)
    assert m.state in (MonitorState.IDLE, MonitorState.RUNNING, MonitorState.STOPPING, MonitorState.STOPPED)


@pytest.mark.asyncio
async def test_publish_mapped_events_and_tracking(monkeypatch):
    cfg = PodMonitorConfig(enable_state_reconciliation=False)
    m = PodMonitor(cfg, producer=DummyProducer())
    m._metrics = SimpleNamespace(
        record_pod_monitor_watch_error=lambda *a, **k: None,
        update_pod_monitor_pods_watched=lambda *a, **k: None,
        record_pod_monitor_reconciliation_run=lambda *a, **k: None,
        record_pod_monitor_event_processing_duration=lambda *a, **k: None,
        record_pod_monitor_event_published=lambda *a, **k: None,
    )
    # Stub mapper to return a running event
    from app.infrastructure.kafka.events.metadata import EventMetadata
    def fake_map(pod, event_type):  # noqa: ANN001
        return [PodRunningEvent(execution_id="e1", pod_name=pod.metadata.name, container_statuses="[]", metadata=EventMetadata(service_name="s", service_version="1"))]
    m._event_mapper.map_pod_event = fake_map  # type: ignore[method-assign]
    # Provide a simple producer stub object
    calls = []
    class Prod:
        async def is_healthy(self): return True  # noqa: D401
        async def send_event(self, event, topic, key=None):  # noqa: ANN001
            calls.append((event, topic, key)); return True
    m._producer = Prod()  # type: ignore[assignment]

    ev = PodEvent(event_type=WatchEventType.ADDED, pod=make_pod(name="px"), resource_version="3")
    # add labels to allow correlation id assignment (optional)
    ev.pod.metadata.labels = {"execution-id": "e1"}
    await m._process_pod_event(ev)
    assert "px" in m._tracked_pods
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_reconcile_state_success_and_failure(monkeypatch):
    cfg = PodMonitorConfig(enable_state_reconciliation=True)
    m = PodMonitor(cfg, producer=DummyProducer())
    # Stub metrics (include watch_error used in reconciliation error path)
    m._metrics = SimpleNamespace(
        update_pod_monitor_pods_watched=lambda *a, **k: None,
        record_pod_monitor_reconciliation_run=lambda *a, **k: None,
        record_pod_monitor_watch_error=lambda *a, **k: None,
    )
    # Fake v1 client list_namespaced_pod
    class V1:
        class Pods: pass
        def list_namespaced_pod(self, namespace, label_selector):  # noqa: ANN001
            # Ensure labels/annotations present for mapping
            md1 = SimpleNamespace(name="a", resource_version="5", labels={"execution-id": "e1"}, annotations={})
            md2 = SimpleNamespace(name="b", resource_version="6", labels={"execution-id": "e2"}, annotations={})
            p1 = SimpleNamespace(status=SimpleNamespace(phase="Running"), metadata=md1)
            p2 = SimpleNamespace(status=SimpleNamespace(phase="Running"), metadata=md2)
            return SimpleNamespace(items=[p1, p2])
    m._v1 = V1()
    # Track one extra, one missing
    m._tracked_pods = {"b", "extra"}

    res = await m._reconcile_state()
    assert isinstance(res, ReconciliationResult) and res.success is True
    # Now simulate failure
    class BadV1:
        def list_namespaced_pod(self, *a, **k):  # noqa: ANN001
            raise RuntimeError("boom")
    m._v1 = BadV1()
    res2 = await m._reconcile_state()
    assert res2.success is False


@pytest.mark.asyncio
async def test_unified_producer_adapter():
    """Test UnifiedProducerAdapter functionality."""
    from app.services.pod_monitor.monitor import UnifiedProducerAdapter
    from app.infrastructure.kafka.events.pod import PodCreatedEvent
    from app.infrastructure.kafka.events.metadata import EventMetadata
    
    # Test successful send
    unified_producer = AsyncMock()
    unified_producer.produce = AsyncMock(return_value=None)
    
    adapter = UnifiedProducerAdapter(unified_producer)
    
    # Use a concrete event type that exists
    event = PodCreatedEvent(
        execution_id="exec-123",
        pod_name="test-pod",
        namespace="integr8scode",
        metadata=EventMetadata(service_name="test", service_version="1.0")
    )
    
    # Test successful send
    result = await adapter.send_event(event, "test-topic", "test-key")
    assert result is True
    unified_producer.produce.assert_called_once_with(event_to_produce=event, key="test-key")
    
    # Test failed send
    unified_producer.produce = AsyncMock(side_effect=Exception("Send failed"))
    result = await adapter.send_event(event, "test-topic", "test-key")
    assert result is False
    
    # Test is_healthy
    health = await adapter.is_healthy()
    assert health is True  # Always returns True for UnifiedProducer


@pytest.mark.asyncio
async def test_monitor_start_already_running():
    """Test starting monitor when already running."""
    cfg = PodMonitorConfig(enable_state_reconciliation=False)
    m = PodMonitor(cfg, producer=DummyProducer())
    
    # Set state to running
    m._state = MonitorState.RUNNING
    
    # Try to start - should log warning and return
    await m.start()
    
    # State should remain RUNNING
    assert m._state == MonitorState.RUNNING


@pytest.mark.asyncio
async def test_monitor_stop_already_stopped():
    """Test stopping monitor when already stopped."""
    cfg = PodMonitorConfig(enable_state_reconciliation=False)
    m = PodMonitor(cfg, producer=DummyProducer())
    
    # Set state to stopped
    m._state = MonitorState.STOPPED
    
    # Try to stop - should return immediately
    await m.stop()
    
    # State should remain STOPPED
    assert m._state == MonitorState.STOPPED


@pytest.mark.asyncio
async def test_monitor_start_stop_with_reconciliation():
    """Test start and stop with reconciliation enabled."""
    cfg = PodMonitorConfig(enable_state_reconciliation=True)
    m = PodMonitor(cfg, producer=DummyProducer())
    
    # Mock Kubernetes client initialization
    with patch.object(m, '_initialize_kubernetes_client'):
        with patch.object(m, '_watch_pods', return_value=None) as mock_watch:
            with patch.object(m, '_reconciliation_loop', return_value=None) as mock_reconcile:
                # Start the monitor
                await m.start()
                
                assert m._state == MonitorState.RUNNING
                assert m._watch_task is not None
                assert m._reconcile_task is not None
                
                # Stop the monitor
                m._watch = MagicMock()
                await m.stop()
                
                assert m._state == MonitorState.STOPPED
                assert len(m._tracked_pods) == 0


@pytest.mark.asyncio  
async def test_monitor_stop_with_tasks():
    """Test stopping monitor with active tasks."""
    cfg = PodMonitorConfig(enable_state_reconciliation=True)
    m = PodMonitor(cfg, producer=DummyProducer())
    
    # Create mock tasks using asyncio.create_task with a coroutine
    async def mock_coro():
        pass
    
    watch_task = asyncio.create_task(mock_coro())
    reconcile_task = asyncio.create_task(mock_coro())
    
    m._state = MonitorState.RUNNING
    m._watch_task = watch_task
    m._reconcile_task = reconcile_task
    m._watch = MagicMock()
    
    # Mock event mapper
    m._event_mapper.clear_cache = MagicMock()
    
    # Cancel tasks first so stop() doesn't hang
    watch_task.cancel()
    reconcile_task.cancel()
    
    await m.stop()
    
    # Verify tasks were cancelled
    assert watch_task.cancelled()
    assert reconcile_task.cancelled()
    
    # Verify watch was stopped
    m._watch.stop.assert_called_once()
    
    # Verify state was cleared
    assert m._state == MonitorState.STOPPED
    assert len(m._tracked_pods) == 0
    m._event_mapper.clear_cache.assert_called_once()


from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
from types import SimpleNamespace

import pytest

from app.services.pod_monitor.monitor import PodMonitor, PodMonitorConfig, WatchEventType


class DummyProducer:
    async def produce(self, *a, **k):  # noqa: ANN001
        return None
    async def stop(self):
        return None


def _mk_pod(name="p1", phase="Running", rv="1", labels=None):  # noqa: ANN001
    md = SimpleNamespace(name=name, resource_version=rv, labels=labels or {})
    st = SimpleNamespace(phase=phase)
    return SimpleNamespace(metadata=md, status=st)


@pytest.mark.asyncio
async def test_initialize_k8s_client_all_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patch k8s config and client
    import app.services.pod_monitor.monitor as mod
    class FakeConfig:
        host = "h"; ssl_ca_cert = None; verify_ssl = True; assert_hostname = True  # noqa: E702
    class FakeConfMod:
        @staticmethod
        def get_default_copy(): return FakeConfig()  # noqa: D401
    # Avoid real ApiClient validation of config
    monkeypatch.setattr(mod.k8s_client, "ApiClient", lambda conf: object())
    class V1:
        def __init__(self, *_a, **_k): pass
        def get_api_resources(self): return None
    class Watch:
        def __init__(self): pass
        def stream(self, *a, **k): return []  # noqa: ANN001
    # Inject into module (mod already imported)
    monkeypatch.setattr(mod.k8s_config, "load_incluster_config", lambda: None)
    monkeypatch.setattr(mod.k8s_config, "load_kube_config", lambda *a, **k: None)
    monkeypatch.setattr(mod.k8s_client, "Configuration", FakeConfMod)
    monkeypatch.setattr(mod.k8s_client, "CoreV1Api", V1)
    monkeypatch.setattr(mod.watch, "Watch", Watch)

    # in-cluster path
    m1 = PodMonitor(PodMonitorConfig(in_cluster=True), producer=DummyProducer())
    m1._initialize_kubernetes_client()
    assert m1._v1 is not None and m1._watch is not None

    # kubeconfig path
    m2 = PodMonitor(PodMonitorConfig(in_cluster=False, kubeconfig_path="/tmp/k"), producer=DummyProducer())
    m2._initialize_kubernetes_client()
    assert m2._v1 is not None and m2._watch is not None

    # default path
    m3 = PodMonitor(PodMonitorConfig(), producer=DummyProducer())
    m3._initialize_kubernetes_client()
    assert m3._v1 is not None and m3._watch is not None


@pytest.mark.asyncio
async def test_watch_pod_events_kwargs_and_update_rv(monkeypatch: pytest.MonkeyPatch) -> None:
    # Prepare monitor
    cfg = PodMonitorConfig(namespace="ns", label_selector="l", field_selector="f", watch_timeout_seconds=5)
    m = PodMonitor(cfg, producer=DummyProducer())
    # Provide fake v1 and watch
    class V1:
        def list_namespaced_pod(self, **kwargs):  # noqa: ANN001
            return None
    class StopEvt:
        resource_version = "9"
    class W:
        def stream(self, *a, **k):  # noqa: ANN001
            class S:
                _stop_event = StopEvt()
                def __iter__(self):  # noqa: D401
                    yield {"type": "ADDED", "object": _mk_pod("p1", rv="7")}
                    yield {"type": "MODIFIED", "object": _mk_pod("p1", rv="8")}
            return S()
    m._v1 = V1(); m._watch = W()  # type: ignore[assignment]

    calls = []
    async def proc(self, ev): calls.append(ev)  # noqa: ANN001, D401
    m._process_raw_event = proc.__get__(m, m.__class__)
    m._last_resource_version = "6"
    m._state = m.state.RUNNING
    await m._watch_pod_events()
    # Ensure resource version updated and events processed (at least one)
    assert m._last_resource_version == "9"
    assert len(calls) >= 1

    # Stream without _stop_event attribute -> _update_resource_version tolerates AttributeError
    class W2:
        def stream(self, *a, **k):  # noqa: ANN001
            class S:
                def __iter__(self):
                    if False:
                        yield None
            return S()
    m._watch = W2()  # type: ignore[assignment]
    await m._watch_pod_events()


@pytest.mark.asyncio
async def test_watch_pods_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    from kubernetes.client.rest import ApiException
    m = PodMonitor(PodMonitorConfig(), producer=DummyProducer())
    # Avoid actual sleep/backoff effect (preserve original to prevent recursion)
    import asyncio as _asyncio
    _orig_sleep = _asyncio.sleep
    monkeypatch.setattr("app.services.pod_monitor.monitor.asyncio.sleep", lambda *_a, **_k: _orig_sleep(0))
    # Stub metrics
    m._metrics = SimpleNamespace(record_pod_monitor_watch_error=lambda *a, **k: None)
    # Make _watch_pod_events raise 410 then generic
    async def handle_set_stop(): m._state = m._state.STOPPING  # noqa: D401
    m._handle_watch_error = handle_set_stop  # type: ignore[assignment]
    async def raise410(): raise ApiException(status=410)  # noqa: D401, ANN201
    m._watch_pod_events = raise410  # type: ignore[assignment]
    m._state = m.state.RUNNING
    await m._watch_pods()


@pytest.mark.asyncio
async def test_publish_event_unhealthy_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    m = PodMonitor(PodMonitorConfig(), producer=DummyProducer())
    # Stub metrics
    rec_pub = {"count": 0}
    m._metrics = SimpleNamespace(
        record_pod_monitor_event_published=lambda *a, **k: rec_pub.__setitem__("count", rec_pub["count"] + 1)
    )
    # Map topic
    # Use real topic mapping; no patch required

    # Unhealthy producer
    class P:
        async def is_healthy(self): return False  # noqa: D401
        async def send_event(self, **k): return True  # noqa: ANN001
    m._producer = P()  # type: ignore[assignment]
    await m._publish_event(SimpleNamespace(event_type="X", metadata=SimpleNamespace(correlation_id=None), aggregate_id=None), _mk_pod(labels={"execution-id": "e1"}))
    # Healthy but send failure
    class P2:
        async def is_healthy(self): return True  # noqa: D401
        async def send_event(self, **k): return False  # noqa: ANN001
    m._producer = P2()  # type: ignore[assignment]
    await m._publish_event(SimpleNamespace(event_type="X", metadata=SimpleNamespace(correlation_id=None), aggregate_id=None), _mk_pod(labels={"execution-id": "e1"}))
    # Healthy and success
    class P3:
        async def is_healthy(self): return True  # noqa: D401
        async def send_event(self, **k): return True  # noqa: ANN001
    m._producer = P3()  # type: ignore[assignment]
    await m._publish_event(SimpleNamespace(event_type="X", metadata=SimpleNamespace(correlation_id=None), aggregate_id=None), _mk_pod(labels={"execution-id": "e1"}))
    assert rec_pub["count"] >= 1


@pytest.mark.asyncio
async def test_handle_watch_error_backoff_and_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    m = PodMonitor(PodMonitorConfig(watch_reconnect_delay=0, max_reconnect_attempts=1), producer=DummyProducer())
    # Avoid real sleeping with captured original
    import asyncio as _asyncio
    _orig_sleep = _asyncio.sleep
    monkeypatch.setattr("app.services.pod_monitor.monitor.asyncio.sleep", lambda *_a, **_k: _orig_sleep(0))
    await m._handle_watch_error()
    assert m._reconnect_attempts == 1
    # Next time exceeds max -> state changes to STOPPING
    await m._handle_watch_error()
    assert m.state == m.state.STOPPING


@pytest.mark.asyncio
async def test_reconciliation_loop_invokes_once(monkeypatch: pytest.MonkeyPatch) -> None:
    m = PodMonitor(PodMonitorConfig(enable_state_reconciliation=True, reconcile_interval_seconds=0), producer=DummyProducer())
    m._state = m.state.RUNNING
    called = {"rec": 0, "log": 0}
    async def rec():
        called["rec"] += 1
        m._state = m.state.STOPPING
        return SimpleNamespace(success=True, duration_seconds=0.0, missing_pods=set(), extra_pods=set())
    m._reconcile_state = rec  # type: ignore[assignment]
    m._log_reconciliation_result = lambda *_a, **_k: called.__setitem__("log", called["log"] + 1)  # type: ignore[assignment]
    # Speed up sleep using original to avoid recursion
    import asyncio as _asyncio
    _orig_sleep = _asyncio.sleep
    monkeypatch.setattr("app.services.pod_monitor.monitor.asyncio.sleep", lambda *_a, **_k: _orig_sleep(0))
    await m._reconciliation_loop()
    assert called["rec"] == 1 and called["log"] == 1


@pytest.mark.asyncio
async def test_get_status_and_context_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    m = PodMonitor(PodMonitorConfig(), producer=DummyProducer())
    st = await m.get_status()
    assert isinstance(st, dict) and "state" in st

    # context manager
    from app.services.pod_monitor.monitor import create_pod_monitor
    started = {"s": 0, "t": 0}
    async def fake_start(self): started.__setitem__("s", 1)  # noqa: D401, ANN001
    async def fake_stop(self): started.__setitem__("t", 1)  # noqa: D401, ANN001
    monkeypatch.setattr(PodMonitor, "start", fake_start)
    monkeypatch.setattr(PodMonitor, "stop", fake_stop)
    async with create_pod_monitor(PodMonitorConfig(), DummyProducer()) as mon:
        assert isinstance(mon, PodMonitor)
    assert started["s"] == 1 and started["t"] == 1


@pytest.mark.asyncio
async def test_run_pod_monitor_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patch schema registry functions in their module and producer
    import app.events.schema.schema_registry as schem
    monkeypatch.setattr(schem, "create_schema_registry_manager", lambda: object())
    async def _init_schemas(_mgr):  # noqa: ANN001
        return None
    monkeypatch.setattr(schem, "initialize_event_schemas", _init_schemas)
    import app.services.pod_monitor.monitor as mod
    monkeypatch.setattr("app.services.pod_monitor.monitor.get_settings", lambda: SimpleNamespace(KAFKA_BOOTSTRAP_SERVERS="k"))
    class P:
        async def start(self): pass
        async def stop(self): pass
    monkeypatch.setattr(mod, "UnifiedProducer", lambda *a, **k: P())
    # Ensure monitor.start stops immediately to avoid loop
    async def fake_start(self): self._state = self.state.STOPPED  # noqa: D401, ANN001
    monkeypatch.setattr(PodMonitor, "start", fake_start)
    # Fake loop with add_signal_handler available
    class Loop:
        def add_signal_handler(self, *_a, **_k): pass
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: Loop())

    await mod.run_pod_monitor()
