import asyncio
import types
import pytest

from app.services.pod_monitor.config import PodMonitorConfig
from app.services.pod_monitor.monitor import PodMonitor
from tests.helpers.k8s_fakes import make_pod, make_watch, FakeApi


pytestmark = pytest.mark.unit


# ===== Shared stubs for k8s mocking =====

class _Cfg:
    host = "https://k8s"
    ssl_ca_cert = None


class _K8sConfig:
    def load_incluster_config(self): pass
    def load_kube_config(self, config_file=None): pass  # noqa: ARG002


class _Conf:
    @staticmethod
    def get_default_copy():
        return _Cfg()


class _ApiClient:
    def __init__(self, cfg): pass  # noqa: ARG002


class _Core:
    def __init__(self, api): pass  # noqa: ARG002
    def get_api_resources(self): return None


class _Watch:
    def __init__(self): pass
    def stop(self): pass


class _SpyMapper:
    def __init__(self) -> None:
        self.cleared = False
    def clear_cache(self) -> None:
        self.cleared = True


class _StubV1:
    def get_api_resources(self):
        return None


class _StubWatch:
    def stop(self):
        return None


class _FakeProducer:
    async def start(self):
        return None
    async def stop(self):
        return None
    async def produce(self, *a, **k):  # noqa: ARG002
        return None
    @property
    def _producer(self):
        return object()


def _patch_k8s(monkeypatch, k8s_config=None, conf=None, api_client=None, core=None, watch=None):
    """Helper to patch k8s modules with defaults or custom stubs."""
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_config", k8s_config or _K8sConfig())
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_client.Configuration", conf or _Conf)
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_client.ApiClient", api_client or _ApiClient)
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_client.CoreV1Api", core or _Core)
    monkeypatch.setattr("app.services.pod_monitor.monitor.watch", types.SimpleNamespace(Watch=watch or _Watch))


# ===== Tests =====

@pytest.mark.asyncio
async def test_start_and_stop_lifecycle(monkeypatch) -> None:
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = False

    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._initialize_kubernetes_client = lambda: None
    spy = _SpyMapper()
    pm._event_mapper = spy
    pm._v1 = _StubV1()
    pm._watch = _StubWatch()
    async def _quick_watch():
        return None
    pm._watch_pods = _quick_watch

    await pm.start()
    assert pm.state.name == "RUNNING"

    await pm.stop()
    assert pm.state.name == "STOPPED" and spy.cleared is True


def test_initialize_kubernetes_client_paths(monkeypatch) -> None:
    cfg = PodMonitorConfig()
    _patch_k8s(monkeypatch)

    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._initialize_kubernetes_client()
    assert pm._v1 is not None and pm._watch is not None


@pytest.mark.asyncio
async def test_watch_pod_events_flow_and_publish(monkeypatch) -> None:
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = False

    pm = PodMonitor(cfg, producer=_FakeProducer())

    from app.services.pod_monitor.event_mapper import PodEventMapper as PEM
    pm._event_mapper = PEM(k8s_api=FakeApi("{}"))

    class V1:
        def list_namespaced_pod(self, **kwargs):  # noqa: ARG002
            return None

    pm._v1 = V1()
    pod = make_pod(name="p", phase="Succeeded", labels={"execution-id": "e1"}, term_exit=0, resource_version="rv1")
    pm._watch = make_watch([{"type": "MODIFIED", "object": pod}], resource_version="rv2")

    pm._state = pm.state.__class__.RUNNING
    await pm._watch_pod_events()
    assert pm._last_resource_version == "rv2"


@pytest.mark.asyncio
async def test_process_raw_event_invalid_and_handle_watch_error(monkeypatch) -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())

    await pm._process_raw_event({})

    pm.config.watch_reconnect_delay = 0
    pm._reconnect_attempts = 0
    await pm._handle_watch_error()
    await pm._handle_watch_error()
    assert pm._reconnect_attempts >= 2


@pytest.mark.asyncio
async def test_unified_producer_adapter() -> None:
    from app.services.pod_monitor.monitor import UnifiedProducerAdapter

    class _TrackerProducer:
        def __init__(self):
            self.events = []
            self._producer = object()
        async def produce(self, event_to_produce, key=None):
            self.events.append((event_to_produce, key))

    tracker = _TrackerProducer()
    adapter = UnifiedProducerAdapter(tracker)

    class _Event:
        pass
    event = _Event()
    success = await adapter.send_event(event, "topic", "key")
    assert success is True and tracker.events == [(event, "key")]

    assert await adapter.is_healthy() is True

    class _FailProducer:
        _producer = object()
        async def produce(self, *a, **k):
            raise RuntimeError("boom")

    fail_adapter = UnifiedProducerAdapter(_FailProducer())
    success = await fail_adapter.send_event(_Event(), "topic")
    assert success is False

    class _NoneProducer:
        _producer = None
    assert await UnifiedProducerAdapter(_NoneProducer()).is_healthy() is False


@pytest.mark.asyncio
async def test_get_status() -> None:
    cfg = PodMonitorConfig()
    cfg.namespace = "test-ns"
    cfg.label_selector = "app=test"
    cfg.enable_state_reconciliation = True

    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._tracked_pods = {"pod1", "pod2"}
    pm._reconnect_attempts = 3
    pm._last_resource_version = "v123"

    status = await pm.get_status()
    assert "idle" in status["state"].lower()
    assert status["tracked_pods"] == 2
    assert status["reconnect_attempts"] == 3
    assert status["last_resource_version"] == "v123"
    assert status["config"]["namespace"] == "test-ns"
    assert status["config"]["label_selector"] == "app=test"
    assert status["config"]["enable_reconciliation"] is True


@pytest.mark.asyncio
async def test_reconciliation_loop_and_state(monkeypatch) -> None:
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = True
    cfg.reconcile_interval_seconds = 0.01

    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._state = pm.state.__class__.RUNNING

    reconcile_called = []
    async def mock_reconcile():
        reconcile_called.append(True)
        from app.services.pod_monitor.monitor import ReconciliationResult
        return ReconciliationResult(
            missing_pods={"p1"},
            extra_pods={"p2"},
            duration_seconds=0.1,
            success=True
        )

    pm._reconcile_state = mock_reconcile

    evt = asyncio.Event()
    async def wrapped_reconcile():
        res = await mock_reconcile()
        evt.set()
        return res
    pm._reconcile_state = wrapped_reconcile

    task = asyncio.create_task(pm._reconciliation_loop())
    await asyncio.wait_for(evt.wait(), timeout=1.0)
    pm._state = pm.state.__class__.STOPPED
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(reconcile_called) > 0


@pytest.mark.asyncio
async def test_reconcile_state_success(monkeypatch) -> None:
    cfg = PodMonitorConfig()
    cfg.namespace = "test"
    cfg.label_selector = "app=test"

    pm = PodMonitor(cfg, producer=_FakeProducer())

    def sync_list(namespace, label_selector):  # noqa: ARG002
        return types.SimpleNamespace(
            items=[
                make_pod(name="pod1", phase="Running", resource_version="v1"),
                make_pod(name="pod2", phase="Running", resource_version="v1"),
            ]
        )

    pm._v1 = types.SimpleNamespace(list_namespaced_pod=sync_list)
    pm._tracked_pods = {"pod2", "pod3"}

    processed = []
    async def mock_process(event):
        processed.append(event.pod.metadata.name)
    pm._process_pod_event = mock_process

    result = await pm._reconcile_state()

    assert result.success is True
    assert result.missing_pods == {"pod1"}
    assert result.extra_pods == {"pod3"}
    assert "pod1" in processed
    assert "pod3" not in pm._tracked_pods


@pytest.mark.asyncio
async def test_reconcile_state_no_v1_api() -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._v1 = None

    result = await pm._reconcile_state()
    assert result.success is False
    assert result.error == "K8s API not initialized"


@pytest.mark.asyncio
async def test_reconcile_state_exception() -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())

    class FailV1:
        def list_namespaced_pod(self, *a, **k):
            raise RuntimeError("API error")

    pm._v1 = FailV1()

    result = await pm._reconcile_state()
    assert result.success is False
    assert "API error" in result.error

@pytest.mark.asyncio
async def test_process_pod_event_full_flow() -> None:
    from app.services.pod_monitor.monitor import PodEvent, WatchEventType

    cfg = PodMonitorConfig()
    cfg.ignored_pod_phases = ["Unknown"]

    pm = PodMonitor(cfg, producer=_FakeProducer())

    class MockMapper:
        def map_pod_event(self, pod, event_type):
            class Event:
                event_type = types.SimpleNamespace(value="test_event")
                metadata = types.SimpleNamespace(correlation_id=None)
                aggregate_id = "agg1"
            return [Event()]

    pm._event_mapper = MockMapper()

    published = []
    async def mock_publish(event, pod):
        published.append(event)
    pm._publish_event = mock_publish

    event = PodEvent(
        event_type=WatchEventType.ADDED,
        pod=make_pod(name="test-pod", phase="Running"),
        resource_version="v1",
    )

    await pm._process_pod_event(event)
    assert "test-pod" in pm._tracked_pods
    assert pm._last_resource_version == "v1"
    assert len(published) == 1

    event_del = PodEvent(
        event_type=WatchEventType.DELETED,
        pod=make_pod(name="test-pod", phase="Succeeded"),
        resource_version="v2",
    )

    await pm._process_pod_event(event_del)
    assert "test-pod" not in pm._tracked_pods
    assert pm._last_resource_version == "v2"

    event_ignored = PodEvent(
        event_type=WatchEventType.ADDED,
        pod=make_pod(name="ignored-pod", phase="Unknown"),
        resource_version="v3",
    )

    published.clear()
    await pm._process_pod_event(event_ignored)
    assert len(published) == 0


@pytest.mark.asyncio
async def test_process_pod_event_exception_handling() -> None:
    from app.services.pod_monitor.monitor import PodEvent, WatchEventType

    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())

    class FailMapper:
        def map_pod_event(self, pod, event_type):
            raise RuntimeError("Mapping failed")

    pm._event_mapper = FailMapper()

    event = PodEvent(
        event_type=WatchEventType.ADDED,
        pod=make_pod(name="fail-pod", phase="Pending"),
        resource_version=None
    )

    await pm._process_pod_event(event)


@pytest.mark.asyncio
async def test_publish_event_full_flow() -> None:
    from app.domain.enums.events import EventType

    cfg = PodMonitorConfig()

    published = []

    class TrackerProducer:
        def __init__(self):
            self._producer = object()
        async def produce(self, event_to_produce, key=None):
            published.append((event_to_produce, key))
        async def is_healthy(self):
            return True

    from app.services.pod_monitor.monitor import UnifiedProducerAdapter
    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._producer = UnifiedProducerAdapter(TrackerProducer())

    class Event:
        event_type = EventType.EXECUTION_COMPLETED
        metadata = types.SimpleNamespace(correlation_id=None)
        aggregate_id = "exec1"
        execution_id = "exec1"

    pod = make_pod(name="test-pod", phase="Succeeded", labels={"execution-id": "exec1"})
    await pm._publish_event(Event(), pod)

    assert len(published) == 1
    assert published[0][1] == "exec1"

    class UnhealthyProducer:
        _producer = None
        async def is_healthy(self):
            return False

    pm._producer = UnifiedProducerAdapter(UnhealthyProducer())
    published.clear()
    await pm._publish_event(Event(), pod)
    assert len(published) == 0


@pytest.mark.asyncio
async def test_publish_event_exception_handling() -> None:
    from app.domain.enums.events import EventType

    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())

    class ExceptionProducer:
        _producer = object()
        async def is_healthy(self):
            raise RuntimeError("Health check failed")

    from app.services.pod_monitor.monitor import UnifiedProducerAdapter
    pm._producer = UnifiedProducerAdapter(ExceptionProducer())

    class Event:
        event_type = EventType.EXECUTION_STARTED

    class Pod:
        metadata = None
        status = None

    await pm._publish_event(Event(), Pod())


@pytest.mark.asyncio
async def test_handle_watch_error_max_attempts() -> None:
    cfg = PodMonitorConfig()
    cfg.max_reconnect_attempts = 2

    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._state = pm.state.__class__.RUNNING
    pm._reconnect_attempts = 2

    await pm._handle_watch_error()

    assert pm._state == pm.state.__class__.STOPPING


@pytest.mark.asyncio
async def test_watch_pods_main_loop(monkeypatch) -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._state = pm.state.__class__.RUNNING

    watch_count = []
    async def mock_watch():
        watch_count.append(1)
        if len(watch_count) > 2:
            pm._state = pm.state.__class__.STOPPED

    async def mock_handle_error():
        pass

    pm._watch_pod_events = mock_watch
    pm._handle_watch_error = mock_handle_error

    await pm._watch_pods()
    assert len(watch_count) > 2


@pytest.mark.asyncio
async def test_watch_pods_api_exception(monkeypatch) -> None:
    from kubernetes.client.rest import ApiException

    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._state = pm.state.__class__.RUNNING

    async def mock_watch():
        raise ApiException(status=410)

    error_handled = []
    async def mock_handle():
        error_handled.append(True)
        pm._state = pm.state.__class__.STOPPED

    pm._watch_pod_events = mock_watch
    pm._handle_watch_error = mock_handle

    await pm._watch_pods()

    assert pm._last_resource_version is None
    assert len(error_handled) > 0


@pytest.mark.asyncio
async def test_watch_pods_generic_exception(monkeypatch) -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._state = pm.state.__class__.RUNNING

    async def mock_watch():
        raise RuntimeError("Unexpected error")

    error_handled = []
    async def mock_handle():
        error_handled.append(True)
        pm._state = pm.state.__class__.STOPPED

    pm._watch_pod_events = mock_watch
    pm._handle_watch_error = mock_handle

    await pm._watch_pods()
    assert len(error_handled) > 0


@pytest.mark.asyncio
async def test_create_pod_monitor_context_manager(monkeypatch) -> None:
    from app.services.pod_monitor.monitor import create_pod_monitor

    _patch_k8s(monkeypatch)

    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = False

    producer = _FakeProducer()

    async with create_pod_monitor(cfg, producer) as monitor:
        assert monitor.state == monitor.state.__class__.RUNNING

    assert monitor.state == monitor.state.__class__.STOPPED


@pytest.mark.asyncio
async def test_start_already_running() -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._state = pm.state.__class__.RUNNING

    await pm.start()


@pytest.mark.asyncio
async def test_stop_already_stopped() -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._state = pm.state.__class__.STOPPED

    await pm.stop()


@pytest.mark.asyncio
async def test_stop_with_tasks() -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._state = pm.state.__class__.RUNNING

    async def dummy_task():
        await asyncio.Event().wait()

    pm._watch_task = asyncio.create_task(dummy_task())
    pm._reconcile_task = asyncio.create_task(dummy_task())
    pm._watch = _StubWatch()
    pm._tracked_pods = {"pod1"}

    await pm.stop()

    assert pm._state == pm.state.__class__.STOPPED
    assert len(pm._tracked_pods) == 0


def test_update_resource_version() -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())

    class Stream:
        _stop_event = types.SimpleNamespace(resource_version="v123")

    pm._update_resource_version(Stream())
    assert pm._last_resource_version == "v123"

    class BadStream:
        pass

    pm._update_resource_version(BadStream())


@pytest.mark.asyncio
async def test_process_raw_event_with_metadata() -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())

    processed = []
    async def mock_process(event):
        processed.append(event)
    pm._process_pod_event = mock_process

    raw_event = {
        'type': 'ADDED',
        'object': types.SimpleNamespace(
            metadata=types.SimpleNamespace(resource_version='v1')
        )
    }

    await pm._process_raw_event(raw_event)
    assert len(processed) == 1
    assert processed[0].resource_version == 'v1'

    raw_event_no_meta = {
        'type': 'MODIFIED',
        'object': types.SimpleNamespace(metadata=None)
    }

    await pm._process_raw_event(raw_event_no_meta)
    assert len(processed) == 2
    assert processed[1].resource_version is None


def test_initialize_kubernetes_client_in_cluster(monkeypatch) -> None:
    cfg = PodMonitorConfig()
    cfg.in_cluster = True

    load_incluster_called = []

    class TrackingK8sConfig:
        def load_incluster_config(self):
            load_incluster_called.append(True)
        def load_kube_config(self, config_file=None): pass  # noqa: ARG002

    _patch_k8s(monkeypatch, k8s_config=TrackingK8sConfig())

    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._initialize_kubernetes_client()

    assert len(load_incluster_called) == 1


def test_initialize_kubernetes_client_with_kubeconfig_path(monkeypatch) -> None:
    cfg = PodMonitorConfig()
    cfg.in_cluster = False
    cfg.kubeconfig_path = "/custom/kubeconfig"

    load_kube_called_with = []

    class TrackingK8sConfig:
        def load_incluster_config(self): pass
        def load_kube_config(self, config_file=None):
            load_kube_called_with.append(config_file)

    class ConfWithCert:
        @staticmethod
        def get_default_copy():
            return types.SimpleNamespace(host="https://k8s", ssl_ca_cert="cert")

    _patch_k8s(monkeypatch, k8s_config=TrackingK8sConfig(), conf=ConfWithCert)

    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._initialize_kubernetes_client()

    assert load_kube_called_with == ["/custom/kubeconfig"]


def test_initialize_kubernetes_client_exception(monkeypatch) -> None:
    cfg = PodMonitorConfig()

    class FailingK8sConfig:
        def load_kube_config(self, config_file=None):
            raise Exception("K8s config error")

    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_config", FailingK8sConfig())

    pm = PodMonitor(cfg, producer=_FakeProducer())

    with pytest.raises(Exception) as exc_info:
        pm._initialize_kubernetes_client()

    assert "K8s config error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_watch_pods_api_exception_other_status(monkeypatch) -> None:
    from kubernetes.client.rest import ApiException

    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._state = pm.state.__class__.RUNNING

    async def mock_watch():
        raise ApiException(status=500)

    error_handled = []
    async def mock_handle():
        error_handled.append(True)
        pm._state = pm.state.__class__.STOPPED

    pm._watch_pod_events = mock_watch
    pm._handle_watch_error = mock_handle

    await pm._watch_pods()
    assert len(error_handled) > 0


@pytest.mark.asyncio
async def test_watch_pod_events_no_watch_or_v1() -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())

    pm._watch = None
    pm._v1 = _StubV1()

    with pytest.raises(RuntimeError) as exc_info:
        await pm._watch_pod_events()

    assert "Watch or API not initialized" in str(exc_info.value)

    pm._watch = _StubWatch()
    pm._v1 = None

    with pytest.raises(RuntimeError) as exc_info:
        await pm._watch_pod_events()

    assert "Watch or API not initialized" in str(exc_info.value)


@pytest.mark.asyncio
async def test_watch_pod_events_with_field_selector() -> None:
    cfg = PodMonitorConfig()
    cfg.field_selector = "status.phase=Running"
    cfg.enable_state_reconciliation = False

    pm = PodMonitor(cfg, producer=_FakeProducer())

    watch_kwargs = []

    class V1:
        def list_namespaced_pod(self, **kwargs):
            watch_kwargs.append(kwargs)
            return None

    class Watch:
        def stream(self, func, **kwargs):
            watch_kwargs.append(kwargs)
            return []

    pm._v1 = V1()
    pm._watch = Watch()
    pm._state = pm.state.__class__.RUNNING

    await pm._watch_pod_events()

    assert any("field_selector" in kw for kw in watch_kwargs)


@pytest.mark.asyncio
async def test_reconciliation_loop_exception() -> None:
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = True
    cfg.reconcile_interval_seconds = 0.01

    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._state = pm.state.__class__.RUNNING

    hit = asyncio.Event()
    async def raising():
        hit.set()
        raise RuntimeError("Reconcile error")
    pm._reconcile_state = raising

    task = asyncio.create_task(pm._reconciliation_loop())
    await asyncio.wait_for(hit.wait(), timeout=1.0)
    pm._state = pm.state.__class__.STOPPED
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_start_with_reconciliation() -> None:
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = True

    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._initialize_kubernetes_client = lambda: None
    pm._v1 = _StubV1()
    pm._watch = _StubWatch()

    async def mock_watch():
        return None

    async def mock_reconcile():
        return None

    pm._watch_pods = mock_watch
    pm._reconciliation_loop = mock_reconcile

    await pm.start()
    assert pm._watch_task is not None
    assert pm._reconcile_task is not None

    await pm.stop()
