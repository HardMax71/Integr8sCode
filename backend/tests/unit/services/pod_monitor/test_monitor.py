import asyncio
import types
import pytest

from app.services.pod_monitor.config import PodMonitorConfig
from app.services.pod_monitor.monitor import PodMonitor


pytestmark = pytest.mark.unit


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
    # Adapter looks at _producer._producer is not None for health
    @property
    def _producer(self):
        return object()


@pytest.mark.asyncio
async def test_start_and_stop_lifecycle(monkeypatch) -> None:
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = False

    pm = PodMonitor(cfg, producer=_FakeProducer())
    # Avoid real k8s client init; keep our spy mapper in place
    pm._initialize_kubernetes_client = lambda: None  # type: ignore[assignment]
    spy = _SpyMapper()
    pm._event_mapper = spy  # type: ignore[assignment]
    pm._v1 = _StubV1()
    pm._watch = _StubWatch()
    pm._watch_pods = lambda: asyncio.sleep(0.1)  # type: ignore[assignment]

    await pm.start()
    assert pm.state.name == "RUNNING"

    await pm.stop()
    assert pm.state.name == "STOPPED" and spy.cleared is True


def test_initialize_kubernetes_client_paths(monkeypatch) -> None:
    cfg = PodMonitorConfig()
    # Create stubs for k8s modules
    class _Cfg:
        host = "https://k8s"
        ssl_ca_cert = None

    class _K8sConfig:
        def load_incluster_config(self): pass  # noqa: D401, E701
        def load_kube_config(self, config_file=None): pass  # noqa: D401, E701, ARG002

    class _Conf:
        @staticmethod
        def get_default_copy():
            return _Cfg()

    class _ApiClient:
        def __init__(self, cfg):  # noqa: ARG002
            pass

    class _Core:
        def __init__(self, api):  # noqa: ARG002
            self._ok = True
        def get_api_resources(self):
            return None

    class _Watch:
        def __init__(self): pass

    # Patch modules used by monitor
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_config", _K8sConfig())
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_client.Configuration", _Conf)
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_client.ApiClient", _ApiClient)
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_client.CoreV1Api", _Core)
    monkeypatch.setattr("app.services.pod_monitor.monitor.watch", types.SimpleNamespace(Watch=_Watch))

    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._initialize_kubernetes_client()
    # After init, client/watch set and event mapper rebuilt
    assert pm._v1 is not None and pm._watch is not None


@pytest.mark.asyncio
async def test_watch_pod_events_flow_and_publish(monkeypatch) -> None:
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = False

    pm = PodMonitor(cfg, producer=_FakeProducer())

    # Use real mapper with fake API so mapping yields events
    class API:
        def read_namespaced_pod_log(self, *a, **k):
            return "{}"  # empty JSON -> defaults

    from app.services.pod_monitor.event_mapper import PodEventMapper as PEM
    pm._event_mapper = PEM(k8s_api=API())

    # Fake v1 and watch
    class V1:
        def list_namespaced_pod(self, **kwargs):  # noqa: ARG002
            return None
    class StopEvent:
        resource_version = "rv2"
    class Stream(list):
        def __init__(self, events):
            super().__init__(events)
            self._stop_event = StopEvent()
    class Watch:
        def stream(self, func, **kwargs):  # noqa: ARG002
            # Construct a pod that maps to completed
            class Terminated:
                def __init__(self, exit_code): self.exit_code=exit_code
            class State:
                def __init__(self, term=None): self.terminated=term; self.running=None; self.waiting=None
            class CS:
                def __init__(self): self.state=State(Terminated(0)); self.name="c"; self.ready=True; self.restart_count=0
            class Status:
                def __init__(self): self.phase="Succeeded"; self.container_statuses=[CS()]
            class Meta:
                def __init__(self): self.name="p"; self.namespace="integr8scode"; self.labels={"execution-id":"e1"}; self.resource_version="rv1"
            class Spec:
                def __init__(self): self.active_deadline_seconds=None; self.node_name=None
            class Pod:
                def __init__(self): self.metadata=Meta(); self.status=Status(); self.spec=Spec()
            pod = Pod()
            pod.metadata.labels = {"execution-id": "e1"}
            return Stream([
                {"type": "MODIFIED", "object": pod},
            ])
    pm._v1 = V1()
    pm._watch = Watch()

    # Speed up
    pm._state = pm.state.__class__.RUNNING
    await pm._watch_pod_events()
    # resource version updated from stream
    assert pm._last_resource_version == "rv2"


@pytest.mark.asyncio
async def test_process_raw_event_invalid_and_handle_watch_error(monkeypatch) -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())

    # Invalid event shape
    await pm._process_raw_event({})

    # Backoff progression without sleeping long
    async def fast_sleep(x):
        return None
    monkeypatch.setattr("asyncio.sleep", fast_sleep)
    pm._reconnect_attempts = 0
    await pm._handle_watch_error()  # 1
    await pm._handle_watch_error()  # 2
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

    # Test send_event success
    class _Event:
        pass
    event = _Event()
    success = await adapter.send_event(event, "topic", "key")
    assert success is True and tracker.events == [(event, "key")]

    # Test is_healthy
    assert await adapter.is_healthy() is True

    # Test send_event failure
    class _FailProducer:
        _producer = object()
        async def produce(self, *a, **k):
            raise RuntimeError("boom")

    fail_adapter = UnifiedProducerAdapter(_FailProducer())
    success = await fail_adapter.send_event(_Event(), "topic")
    assert success is False

    # Test is_healthy with None producer
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
    assert "idle" in status["state"].lower()  # Check state contains idle
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

    # Run reconciliation loop briefly
    task = asyncio.create_task(pm._reconciliation_loop())
    await asyncio.sleep(0.05)
    pm._state = pm.state.__class__.STOPPED
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(reconcile_called) > 0


@pytest.mark.asyncio
async def test_reconcile_state_success(monkeypatch) -> None:
    cfg = PodMonitorConfig()
    cfg.namespace = "test"
    cfg.label_selector = "app=test"

    pm = PodMonitor(cfg, producer=_FakeProducer())

    # Mock K8s API
    class Pod:
        def __init__(self, name):
            self.metadata = types.SimpleNamespace(name=name, resource_version="v1")

    class V1:
        async def list_namespaced_pod(self, namespace, label_selector):
            return types.SimpleNamespace(items=[Pod("pod1"), Pod("pod2")])

    # asyncio.to_thread needs sync function
    def sync_list(*args, **kwargs):
        import asyncio
        return asyncio.run(V1().list_namespaced_pod(*args, **kwargs))

    pm._v1 = types.SimpleNamespace(list_namespaced_pod=sync_list)
    pm._tracked_pods = {"pod2", "pod3"}  # pod1 missing, pod3 extra

    # Mock process_pod_event
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


def test_log_reconciliation_result(caplog) -> None:
    from app.services.pod_monitor.monitor import ReconciliationResult, PodMonitor

    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())

    # Success case
    result = ReconciliationResult(
        missing_pods={"p1", "p2"},
        extra_pods={"p3"},
        duration_seconds=1.5,
        success=True
    )
    pm._log_reconciliation_result(result)
    assert "Reconciliation completed in 1.50s" in caplog.text
    assert "Found 2 missing, 1 extra pods" in caplog.text

    # Failure case
    caplog.clear()
    result_fail = ReconciliationResult(
        missing_pods=set(),
        extra_pods=set(),
        duration_seconds=0.5,
        success=False,
        error="Connection failed"
    )
    pm._log_reconciliation_result(result_fail)
    assert "Reconciliation failed after 0.50s" in caplog.text
    assert "Connection failed" in caplog.text


@pytest.mark.asyncio
async def test_process_pod_event_full_flow() -> None:
    from app.services.pod_monitor.monitor import PodEvent, WatchEventType

    cfg = PodMonitorConfig()
    cfg.ignored_pod_phases = ["Unknown"]

    pm = PodMonitor(cfg, producer=_FakeProducer())

    # Mock event mapper
    class MockMapper:
        def map_pod_event(self, pod, event_type):
            class Event:
                event_type = types.SimpleNamespace(value="test_event")
                metadata = types.SimpleNamespace(correlation_id=None)
                aggregate_id = "agg1"
            return [Event()]

    pm._event_mapper = MockMapper()

    # Mock publish
    published = []
    async def mock_publish(event, pod):
        published.append(event)
    pm._publish_event = mock_publish

    # Create test pod event
    class Pod:
        def __init__(self, name, phase):
            self.metadata = types.SimpleNamespace(name=name)
            self.status = types.SimpleNamespace(phase=phase)

    # Test ADDED event
    event = PodEvent(
        event_type=WatchEventType.ADDED,
        pod=Pod("test-pod", "Running"),
        resource_version="v1"
    )

    await pm._process_pod_event(event)
    assert "test-pod" in pm._tracked_pods
    assert pm._last_resource_version == "v1"
    assert len(published) == 1

    # Test DELETED event
    event_del = PodEvent(
        event_type=WatchEventType.DELETED,
        pod=Pod("test-pod", "Succeeded"),
        resource_version="v2"
    )

    await pm._process_pod_event(event_del)
    assert "test-pod" not in pm._tracked_pods
    assert pm._last_resource_version == "v2"

    # Test ignored phase
    event_ignored = PodEvent(
        event_type=WatchEventType.ADDED,
        pod=Pod("ignored-pod", "Unknown"),
        resource_version="v3"
    )

    published.clear()
    await pm._process_pod_event(event_ignored)
    assert len(published) == 0  # Should be skipped


@pytest.mark.asyncio
async def test_process_pod_event_exception_handling() -> None:
    from app.services.pod_monitor.monitor import PodEvent, WatchEventType

    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())

    # Mock event mapper to raise exception
    class FailMapper:
        def map_pod_event(self, pod, event_type):
            raise RuntimeError("Mapping failed")

    pm._event_mapper = FailMapper()

    class Pod:
        metadata = types.SimpleNamespace(name="fail-pod")
        status = None

    event = PodEvent(
        event_type=WatchEventType.ADDED,
        pod=Pod(),
        resource_version=None
    )

    # Should not raise, just log error
    await pm._process_pod_event(event)


@pytest.mark.asyncio
async def test_publish_event_full_flow() -> None:
    from app.domain.enums.events import EventType

    cfg = PodMonitorConfig()

    # Track published events
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

    # Create test event and pod
    class Event:
        event_type = EventType.EXECUTION_COMPLETED
        metadata = types.SimpleNamespace(correlation_id=None)
        aggregate_id = "exec1"
        execution_id = "exec1"

    class Pod:
        metadata = types.SimpleNamespace(
            name="test-pod",
            labels={"execution-id": "exec1"}
        )
        status = types.SimpleNamespace(phase="Succeeded")

    await pm._publish_event(Event(), Pod())

    assert len(published) == 1
    assert published[0][1] == "exec1"  # key

    # Test unhealthy producer
    class UnhealthyProducer:
        _producer = None
        async def is_healthy(self):
            return False

    pm._producer = UnifiedProducerAdapter(UnhealthyProducer())
    published.clear()
    await pm._publish_event(Event(), Pod())
    assert len(published) == 0  # Should not publish


@pytest.mark.asyncio
async def test_publish_event_exception_handling() -> None:
    from app.domain.enums.events import EventType

    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())

    # Mock producer that raises exception
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

    # Should not raise, just log error
    await pm._publish_event(Event(), Pod())


@pytest.mark.asyncio
async def test_handle_watch_error_max_attempts() -> None:
    cfg = PodMonitorConfig()
    cfg.max_reconnect_attempts = 2

    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._state = pm.state.__class__.RUNNING
    pm._reconnect_attempts = 2

    await pm._handle_watch_error()

    # Should stop after max attempts
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
        # 410 Gone error
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
async def test_create_pod_monitor_context_manager() -> None:
    from app.services.pod_monitor.monitor import create_pod_monitor

    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = False

    producer = _FakeProducer()

    async with create_pod_monitor(cfg, producer) as monitor:
        # Override kubernetes initialization
        monitor._initialize_kubernetes_client = lambda: None
        monitor._v1 = _StubV1()
        monitor._watch = _StubWatch()
        monitor._watch_pods = lambda: asyncio.sleep(0.01)

        # Monitor should be started
        assert monitor.state == monitor.state.__class__.RUNNING

    # Monitor should be stopped after context exit
    assert monitor.state == monitor.state.__class__.STOPPED


@pytest.mark.asyncio
async def test_start_already_running() -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._state = pm.state.__class__.RUNNING

    await pm.start()  # Should log warning and return


@pytest.mark.asyncio
async def test_stop_already_stopped() -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._state = pm.state.__class__.STOPPED

    await pm.stop()  # Should return immediately


@pytest.mark.asyncio
async def test_stop_with_tasks() -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._state = pm.state.__class__.RUNNING

    # Create dummy tasks
    async def dummy_task():
        await asyncio.sleep(10)

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

    # With valid stream
    class Stream:
        _stop_event = types.SimpleNamespace(resource_version="v123")

    pm._update_resource_version(Stream())
    assert pm._last_resource_version == "v123"

    # With invalid stream (no _stop_event)
    class BadStream:
        pass

    pm._update_resource_version(BadStream())  # Should not raise


@pytest.mark.asyncio
async def test_process_raw_event_with_metadata() -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())

    # Mock process_pod_event
    processed = []
    async def mock_process(event):
        processed.append(event)
    pm._process_pod_event = mock_process

    # Valid event with metadata
    raw_event = {
        'type': 'ADDED',
        'object': types.SimpleNamespace(
            metadata=types.SimpleNamespace(resource_version='v1')
        )
    }

    await pm._process_raw_event(raw_event)
    assert len(processed) == 1
    assert processed[0].resource_version == 'v1'

    # Event without metadata
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

    # Create stubs for k8s modules
    load_incluster_called = []

    class _K8sConfig:
        def load_incluster_config(self):
            load_incluster_called.append(True)
        def load_kube_config(self, config_file=None): pass  # noqa: ARG002

    class _Conf:
        @staticmethod
        def get_default_copy():
            return types.SimpleNamespace(host="https://k8s", ssl_ca_cert=None)

    class _ApiClient:
        def __init__(self, cfg): pass  # noqa: ARG002

    class _Core:
        def __init__(self, api):  # noqa: ARG002
            self._ok = True
        def get_api_resources(self):
            return None

    class _Watch:
        def __init__(self): pass

    # Patch modules
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_config", _K8sConfig())
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_client.Configuration", _Conf)
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_client.ApiClient", _ApiClient)
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_client.CoreV1Api", _Core)
    monkeypatch.setattr("app.services.pod_monitor.monitor.watch", types.SimpleNamespace(Watch=_Watch))

    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._initialize_kubernetes_client()

    assert len(load_incluster_called) == 1


def test_initialize_kubernetes_client_with_kubeconfig_path(monkeypatch) -> None:
    cfg = PodMonitorConfig()
    cfg.in_cluster = False
    cfg.kubeconfig_path = "/custom/kubeconfig"

    load_kube_called_with = []

    class _K8sConfig:
        def load_incluster_config(self): pass
        def load_kube_config(self, config_file=None):
            load_kube_called_with.append(config_file)

    class _Conf:
        @staticmethod
        def get_default_copy():
            return types.SimpleNamespace(host="https://k8s", ssl_ca_cert="cert")

    class _ApiClient:
        def __init__(self, cfg): pass  # noqa: ARG002

    class _Core:
        def __init__(self, api):  # noqa: ARG002
            self._ok = True
        def get_api_resources(self):
            return None

    class _Watch:
        def __init__(self): pass

    # Patch modules
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_config", _K8sConfig())
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_client.Configuration", _Conf)
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_client.ApiClient", _ApiClient)
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_client.CoreV1Api", _Core)
    monkeypatch.setattr("app.services.pod_monitor.monitor.watch", types.SimpleNamespace(Watch=_Watch))

    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._initialize_kubernetes_client()

    assert load_kube_called_with == ["/custom/kubeconfig"]


def test_initialize_kubernetes_client_exception(monkeypatch) -> None:
    import pytest
    cfg = PodMonitorConfig()

    class _K8sConfig:
        def load_kube_config(self, config_file=None):
            raise Exception("K8s config error")

    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_config", _K8sConfig())

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
        # Non-410 API error
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
    import pytest
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, producer=_FakeProducer())

    # No watch
    pm._watch = None
    pm._v1 = _StubV1()

    with pytest.raises(RuntimeError) as exc_info:
        await pm._watch_pod_events()

    assert "Watch or API not initialized" in str(exc_info.value)

    # No v1
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

    # Mock v1 and watch
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

    # Check field_selector was included
    assert any("field_selector" in kw for kw in watch_kwargs)


@pytest.mark.asyncio
async def test_reconciliation_loop_exception() -> None:
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = True
    cfg.reconcile_interval_seconds = 0.01

    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._state = pm.state.__class__.RUNNING

    async def mock_reconcile():
        raise RuntimeError("Reconcile error")

    pm._reconcile_state = mock_reconcile

    # Run reconciliation loop briefly
    task = asyncio.create_task(pm._reconciliation_loop())
    await asyncio.sleep(0.05)
    pm._state = pm.state.__class__.STOPPED
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Should handle exception and continue


@pytest.mark.asyncio
async def test_start_with_reconciliation() -> None:
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = True

    pm = PodMonitor(cfg, producer=_FakeProducer())
    pm._initialize_kubernetes_client = lambda: None
    pm._v1 = _StubV1()
    pm._watch = _StubWatch()

    async def mock_watch():
        await asyncio.sleep(0.01)

    async def mock_reconcile():
        await asyncio.sleep(0.01)

    pm._watch_pods = mock_watch
    pm._reconciliation_loop = mock_reconcile

    await pm.start()
    assert pm._watch_task is not None
    assert pm._reconcile_task is not None

    await pm.stop()


@pytest.mark.asyncio
async def test_run_pod_monitor(monkeypatch) -> None:
    from app.services.pod_monitor.monitor import run_pod_monitor

    # Mock all the dependencies
    class MockSchemaRegistry:
        async def start(self): pass
        async def stop(self): pass

    class MockProducer:
        def __init__(self, config, registry): pass
        async def start(self): pass
        async def stop(self): pass
        _producer = object()

    class MockMonitor:
        def __init__(self, config, producer):
            self.state = MockMonitorState()
        async def start(self): pass
        async def stop(self): pass
        async def get_status(self):
            return {"state": "RUNNING"}

    class MockMonitorState:
        RUNNING = "RUNNING"
        def __eq__(self, other):
            return False  # Always return False to exit loop quickly

    async def mock_initialize(*args): pass
    def mock_create_registry(): return MockSchemaRegistry()

    monkeypatch.setattr("app.services.pod_monitor.monitor.initialize_event_schemas", mock_initialize)
    monkeypatch.setattr("app.services.pod_monitor.monitor.create_schema_registry_manager", mock_create_registry)
    monkeypatch.setattr("app.services.pod_monitor.monitor.UnifiedProducer", MockProducer)
    monkeypatch.setattr("app.services.pod_monitor.monitor.PodMonitor", MockMonitor)
    monkeypatch.setattr("asyncio.get_running_loop", lambda: types.SimpleNamespace(
        add_signal_handler=lambda sig, handler: None
    ))

    # Run briefly
    task = asyncio.create_task(run_pod_monitor())
    await asyncio.sleep(0.1)
    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass
