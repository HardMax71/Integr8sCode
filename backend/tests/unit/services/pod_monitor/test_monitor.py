import asyncio
import logging
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.k8s_clients import K8sClients
from app.services.kafka_event_service import KafkaEventService
from app.services.pod_monitor.config import PodMonitorConfig
from app.services.pod_monitor.monitor import PodMonitor, ReconciliationResult, create_pod_monitor

from tests.helpers.k8s_fakes import FakeApi, make_pod, make_watch

pytestmark = pytest.mark.unit

# Test logger for all tests
_test_logger = logging.getLogger("test.pod_monitor")


def _make_kafka_service_mock() -> MagicMock:
    """Create a properly typed mock for KafkaEventService."""
    mock = MagicMock(spec=KafkaEventService)
    mock.published_events = []

    async def _publish(event: Any, key: Any = None) -> str:
        mock.published_events.append((event, key))
        return getattr(event, "event_id", "fake-id")

    mock.publish_base_event = AsyncMock(side_effect=_publish)
    return mock


# ===== Shared stubs for k8s mocking =====


class _Cfg:
    host = "https://k8s"
    ssl_ca_cert: str | None = None


class _K8sConfig:
    def load_incluster_config(self) -> None:
        pass

    def load_kube_config(self, config_file: str | None = None) -> None:
        pass


class _Conf:
    @staticmethod
    def get_default_copy() -> _Cfg:
        return _Cfg()


class _ApiClient:
    def __init__(self, cfg: Any) -> None:
        pass


class _Core:
    def __init__(self, api: Any) -> None:
        pass

    def get_api_resources(self) -> None:
        return None


class _Watch:
    def __init__(self) -> None:
        pass

    def stop(self) -> None:
        pass


class _SpyMapper:
    def __init__(self) -> None:
        self.cleared = False

    def clear_cache(self) -> None:
        self.cleared = True


class _StubV1:
    def get_api_resources(self) -> None:
        return None


class _StubWatch:
    def stop(self) -> None:
        return None


def _patch_k8s(
    monkeypatch: pytest.MonkeyPatch,
    k8s_config: Any = None,
    conf: Any = None,
    api_client: Any = None,
    core: Any = None,
    watch: Any = None,
) -> None:
    """Helper to patch k8s modules with defaults or custom stubs."""
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_config", k8s_config or _K8sConfig())
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_client.Configuration", conf or _Conf)
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_client.ApiClient", api_client or _ApiClient)
    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_client.CoreV1Api", core or _Core)
    monkeypatch.setattr("app.services.pod_monitor.monitor.watch", types.SimpleNamespace(Watch=watch or _Watch))


# ===== Tests =====


@pytest.mark.asyncio
async def test_start_and_stop_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = False

    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)
    pm._initialize_kubernetes_client = lambda: None  # type: ignore[method-assign]
    spy = _SpyMapper()
    pm._event_mapper = spy  # type: ignore[assignment]
    pm._v1 = _StubV1()
    pm._watch = _StubWatch()

    async def _quick_watch() -> None:
        return None

    pm._watch_pods = _quick_watch  # type: ignore[method-assign]

    await pm.__aenter__()
    assert pm.state.name == "RUNNING"

    await pm.aclose()
    assert pm.state.name == "STOPPED" and spy.cleared is True


def test_initialize_kubernetes_client_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = PodMonitorConfig()
    _patch_k8s(monkeypatch)

    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)
    pm._initialize_kubernetes_client()
    assert pm._v1 is not None and pm._watch is not None


@pytest.mark.asyncio
async def test_watch_pod_events_flow_and_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = False

    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)

    from app.services.pod_monitor.event_mapper import PodEventMapper as PEM

    pm._event_mapper = PEM(k8s_api=FakeApi("{}"), logger=_test_logger)

    class V1:
        def list_namespaced_pod(self, **kwargs: Any) -> None:  # noqa: ARG002
            return None

    pm._v1 = V1()
    pod = make_pod(name="p", phase="Succeeded", labels={"execution-id": "e1"}, term_exit=0, resource_version="rv1")
    pm._watch = make_watch([{"type": "MODIFIED", "object": pod}], resource_version="rv2")

    pm._state = pm.state.__class__.RUNNING
    await pm._watch_pod_events()
    assert pm._last_resource_version == "rv2"


@pytest.mark.asyncio
async def test_process_raw_event_invalid_and_handle_watch_error(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)

    await pm._process_raw_event({})

    pm.config.watch_reconnect_delay = 0
    pm._reconnect_attempts = 0
    await pm._handle_watch_error()
    await pm._handle_watch_error()
    assert pm._reconnect_attempts >= 2


@pytest.mark.asyncio
async def test_get_status() -> None:
    cfg = PodMonitorConfig()
    cfg.namespace = "test-ns"
    cfg.label_selector = "app=test"
    cfg.enable_state_reconciliation = True

    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)
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
async def test_reconciliation_loop_and_state(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = True
    cfg.reconcile_interval_seconds = 0.01  # type: ignore[assignment]

    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)
    pm._state = pm.state.__class__.RUNNING

    reconcile_called = []

    async def mock_reconcile() -> ReconciliationResult:
        reconcile_called.append(True)
        return ReconciliationResult(missing_pods={"p1"}, extra_pods={"p2"}, duration_seconds=0.1, success=True)

    pm._reconcile_state = mock_reconcile  # type: ignore[method-assign]

    evt = asyncio.Event()

    async def wrapped_reconcile() -> ReconciliationResult:
        res = await mock_reconcile()
        evt.set()
        return res

    pm._reconcile_state = wrapped_reconcile  # type: ignore[method-assign]

    task = asyncio.create_task(pm._reconciliation_loop())
    await asyncio.wait_for(evt.wait(), timeout=1.0)
    pm._state = pm.state.__class__.STOPPED
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(reconcile_called) > 0


@pytest.mark.asyncio
async def test_reconcile_state_success(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = PodMonitorConfig()
    cfg.namespace = "test"
    cfg.label_selector = "app=test"

    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)

    def sync_list(namespace: str, label_selector: str) -> types.SimpleNamespace:  # noqa: ARG002
        return types.SimpleNamespace(
            items=[
                make_pod(name="pod1", phase="Running", resource_version="v1"),
                make_pod(name="pod2", phase="Running", resource_version="v1"),
            ]
        )

    pm._v1 = types.SimpleNamespace(list_namespaced_pod=sync_list)
    pm._tracked_pods = {"pod2", "pod3"}

    processed = []

    async def mock_process(event: Any) -> None:
        processed.append(event.pod.metadata.name)

    pm._process_pod_event = mock_process  # type: ignore[method-assign]

    result = await pm._reconcile_state()

    assert result.success is True
    assert result.missing_pods == {"pod1"}
    assert result.extra_pods == {"pod3"}
    assert "pod1" in processed
    assert "pod3" not in pm._tracked_pods


@pytest.mark.asyncio
async def test_reconcile_state_no_v1_api() -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)
    pm._v1 = None

    result = await pm._reconcile_state()
    assert result.success is False
    assert result.error == "K8s API not initialized"


@pytest.mark.asyncio
async def test_reconcile_state_exception() -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)

    class FailV1:
        def list_namespaced_pod(self, *a: Any, **k: Any) -> None:
            raise RuntimeError("API error")

    pm._v1 = FailV1()

    result = await pm._reconcile_state()
    assert result.success is False
    assert result.error is not None and "API error" in result.error


@pytest.mark.asyncio
async def test_process_pod_event_full_flow() -> None:
    from app.services.pod_monitor.monitor import PodEvent, WatchEventType

    cfg = PodMonitorConfig()
    cfg.ignored_pod_phases = ["Unknown"]

    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)

    class MockMapper:
        def map_pod_event(self, pod: Any, event_type: Any) -> list[Any]:
            class Event:
                event_type = types.SimpleNamespace(value="test_event")
                metadata = types.SimpleNamespace(correlation_id=None)
                aggregate_id = "agg1"

            return [Event()]

    pm._event_mapper = MockMapper()  # type: ignore[assignment]

    published = []

    async def mock_publish(event: Any, pod: Any) -> None:
        published.append(event)

    pm._publish_event = mock_publish  # type: ignore[method-assign]

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
    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)

    class FailMapper:
        def map_pod_event(self, pod: Any, event_type: Any) -> list[Any]:
            raise RuntimeError("Mapping failed")

    pm._event_mapper = FailMapper()  # type: ignore[assignment]

    event = PodEvent(
        event_type=WatchEventType.ADDED, pod=make_pod(name="fail-pod", phase="Pending"), resource_version=None
    )

    await pm._process_pod_event(event)


@pytest.mark.asyncio
async def test_publish_event_full_flow() -> None:
    from app.domain.enums.events import EventType

    cfg = PodMonitorConfig()
    fake_service = _make_kafka_service_mock()
    pm = PodMonitor(cfg, kafka_event_service=fake_service, logger=_test_logger)

    class Event:
        event_type = EventType.EXECUTION_COMPLETED
        metadata = types.SimpleNamespace(correlation_id=None)
        aggregate_id = "exec1"
        execution_id = "exec1"
        event_id = "evt-123"

    pod = make_pod(name="test-pod", phase="Succeeded", labels={"execution-id": "exec1"})
    await pm._publish_event(Event(), pod)  # type: ignore[arg-type]

    assert len(fake_service.published_events) == 1
    assert fake_service.published_events[0][1] == "exec1"


@pytest.mark.asyncio
async def test_publish_event_exception_handling() -> None:
    from app.domain.enums.events import EventType

    cfg = PodMonitorConfig()

    class FailingKafkaEventService:
        async def publish_base_event(self, event: Any, key: Any = None) -> None:
            raise RuntimeError("Publish failed")

    pm = PodMonitor(cfg, kafka_event_service=FailingKafkaEventService(), logger=_test_logger)  # type: ignore[arg-type]

    class Event:
        event_type = EventType.EXECUTION_STARTED
        metadata = types.SimpleNamespace(correlation_id=None)
        aggregate_id = None
        execution_id = None

    class Pod:
        metadata = None
        status = None

    # Should not raise - errors are caught and logged
    await pm._publish_event(Event(), Pod())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_handle_watch_error_max_attempts() -> None:
    cfg = PodMonitorConfig()
    cfg.max_reconnect_attempts = 2

    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)
    pm._state = pm.state.__class__.RUNNING
    pm._reconnect_attempts = 2

    await pm._handle_watch_error()

    assert pm._state == pm.state.__class__.STOPPING


@pytest.mark.asyncio
async def test_watch_pods_main_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)
    pm._state = pm.state.__class__.RUNNING

    watch_count = []

    async def mock_watch() -> None:
        watch_count.append(1)
        if len(watch_count) > 2:
            pm._state = pm.state.__class__.STOPPED

    async def mock_handle_error() -> None:
        pass

    pm._watch_pod_events = mock_watch  # type: ignore[method-assign]
    pm._handle_watch_error = mock_handle_error  # type: ignore[method-assign]

    await pm._watch_pods()
    assert len(watch_count) > 2


@pytest.mark.asyncio
async def test_watch_pods_api_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    from kubernetes.client.rest import ApiException

    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)
    pm._state = pm.state.__class__.RUNNING

    async def mock_watch() -> None:
        raise ApiException(status=410)

    error_handled = []

    async def mock_handle() -> None:
        error_handled.append(True)
        pm._state = pm.state.__class__.STOPPED

    pm._watch_pod_events = mock_watch  # type: ignore[method-assign]
    pm._handle_watch_error = mock_handle  # type: ignore[method-assign]

    await pm._watch_pods()

    assert pm._last_resource_version is None
    assert len(error_handled) > 0


@pytest.mark.asyncio
async def test_watch_pods_generic_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)
    pm._state = pm.state.__class__.RUNNING

    async def mock_watch() -> None:
        raise RuntimeError("Unexpected error")

    error_handled = []

    async def mock_handle() -> None:
        error_handled.append(True)
        pm._state = pm.state.__class__.STOPPED

    pm._watch_pod_events = mock_watch  # type: ignore[method-assign]
    pm._handle_watch_error = mock_handle  # type: ignore[method-assign]

    await pm._watch_pods()
    assert len(error_handled) > 0


@pytest.mark.asyncio
async def test_create_pod_monitor_context_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_k8s(monkeypatch)

    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = False

    fake_service = _make_kafka_service_mock()

    async with create_pod_monitor(cfg, fake_service, _test_logger) as monitor:
        assert monitor.state.name == "RUNNING"

    assert monitor.state.name == "STOPPED"


@pytest.mark.asyncio
async def test_create_pod_monitor_with_injected_k8s_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test create_pod_monitor with injected K8sClients (DI path)."""
    _patch_k8s(monkeypatch)

    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = False

    fake_service = _make_kafka_service_mock()

    mock_v1 = MagicMock()
    mock_v1.get_api_resources.return_value = None
    mock_k8s_clients = K8sClients(
        api_client=MagicMock(),
        v1=mock_v1,
        apps_v1=MagicMock(),
        networking_v1=MagicMock(),
    )

    async with create_pod_monitor(cfg, fake_service, _test_logger, k8s_clients=mock_k8s_clients) as monitor:
        assert monitor.state.name == "RUNNING"
        assert monitor._clients is mock_k8s_clients
        assert monitor._v1 is mock_v1

    assert monitor.state.name == "STOPPED"


@pytest.mark.asyncio
async def test_start_already_running() -> None:
    """Test idempotent start via __aenter__."""
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)
    # Simulate already started state
    pm._lifecycle_started = True
    pm._state = pm.state.__class__.RUNNING

    # Should be idempotent - just return self
    await pm.__aenter__()


@pytest.mark.asyncio
async def test_stop_already_stopped() -> None:
    """Test idempotent stop via aclose()."""
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)
    pm._state = pm.state.__class__.STOPPED
    # Not started, so aclose should be a no-op

    await pm.aclose()


@pytest.mark.asyncio
async def test_stop_with_tasks() -> None:
    """Test cleanup of tasks on aclose()."""
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)
    pm._state = pm.state.__class__.RUNNING
    pm._lifecycle_started = True  # Simulate started state

    async def dummy_task() -> None:
        await asyncio.Event().wait()

    pm._watch_task = asyncio.create_task(dummy_task())
    pm._reconcile_task = asyncio.create_task(dummy_task())
    pm._watch = _StubWatch()
    pm._tracked_pods = {"pod1"}

    await pm.aclose()

    assert pm._state == pm.state.__class__.STOPPED
    assert len(pm._tracked_pods) == 0


def test_update_resource_version() -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)

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
    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)

    processed = []

    async def mock_process(event: Any) -> None:
        processed.append(event)

    pm._process_pod_event = mock_process  # type: ignore[method-assign]

    raw_event = {
        "type": "ADDED",
        "object": types.SimpleNamespace(metadata=types.SimpleNamespace(resource_version="v1")),
    }

    await pm._process_raw_event(raw_event)
    assert len(processed) == 1
    assert processed[0].resource_version == "v1"

    raw_event_no_meta = {"type": "MODIFIED", "object": types.SimpleNamespace(metadata=None)}

    await pm._process_raw_event(raw_event_no_meta)
    assert len(processed) == 2
    assert processed[1].resource_version is None


def test_initialize_kubernetes_client_in_cluster(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = PodMonitorConfig()
    cfg.in_cluster = True

    load_incluster_called: list[bool] = []

    class TrackingK8sConfig:
        def load_incluster_config(self) -> None:
            load_incluster_called.append(True)

        def load_kube_config(self, config_file: str | None = None) -> None:  # noqa: ARG002
            pass

    _patch_k8s(monkeypatch, k8s_config=TrackingK8sConfig())

    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)
    pm._initialize_kubernetes_client()

    assert len(load_incluster_called) == 1


def test_initialize_kubernetes_client_with_kubeconfig_path(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = PodMonitorConfig()
    cfg.in_cluster = False
    cfg.kubeconfig_path = "/custom/kubeconfig"

    load_kube_called_with: list[str | None] = []

    class TrackingK8sConfig:
        def load_incluster_config(self) -> None:
            pass

        def load_kube_config(self, config_file: str | None = None) -> None:
            load_kube_called_with.append(config_file)

    class ConfWithCert:
        @staticmethod
        def get_default_copy() -> types.SimpleNamespace:
            return types.SimpleNamespace(host="https://k8s", ssl_ca_cert="cert")

    _patch_k8s(monkeypatch, k8s_config=TrackingK8sConfig(), conf=ConfWithCert)

    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)
    pm._initialize_kubernetes_client()

    assert load_kube_called_with == ["/custom/kubeconfig"]


def test_initialize_kubernetes_client_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = PodMonitorConfig()

    class FailingK8sConfig:
        def load_kube_config(self, config_file: str | None = None) -> None:  # noqa: ARG002
            raise Exception("K8s config error")

    monkeypatch.setattr("app.services.pod_monitor.monitor.k8s_config", FailingK8sConfig())

    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)

    with pytest.raises(Exception) as exc_info:
        pm._initialize_kubernetes_client()

    assert "K8s config error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_watch_pods_api_exception_other_status(monkeypatch: pytest.MonkeyPatch) -> None:
    from kubernetes.client.rest import ApiException

    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)
    pm._state = pm.state.__class__.RUNNING

    async def mock_watch() -> None:
        raise ApiException(status=500)

    error_handled: list[bool] = []

    async def mock_handle() -> None:
        error_handled.append(True)
        pm._state = pm.state.__class__.STOPPED

    pm._watch_pod_events = mock_watch  # type: ignore[method-assign]
    pm._handle_watch_error = mock_handle  # type: ignore[method-assign]

    await pm._watch_pods()
    assert len(error_handled) > 0


@pytest.mark.asyncio
async def test_watch_pod_events_no_watch_or_v1() -> None:
    cfg = PodMonitorConfig()
    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)

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

    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)

    watch_kwargs = []

    class V1:
        def list_namespaced_pod(self, **kwargs: Any) -> None:
            watch_kwargs.append(kwargs)
            return None

    class Watch:
        def stream(self, func: Any, **kwargs: Any) -> list[Any]:
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
    cfg.reconcile_interval_seconds = 0.01  # type: ignore[assignment]

    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)
    pm._state = pm.state.__class__.RUNNING

    hit = asyncio.Event()

    async def raising() -> ReconciliationResult:
        hit.set()
        raise RuntimeError("Reconcile error")

    pm._reconcile_state = raising  # type: ignore[method-assign]

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

    pm = PodMonitor(cfg, kafka_event_service=_make_kafka_service_mock(), logger=_test_logger)
    pm._initialize_kubernetes_client = lambda: None  # type: ignore[method-assign]
    pm._v1 = _StubV1()
    pm._watch = _StubWatch()

    async def mock_watch() -> None:
        return None

    async def mock_reconcile() -> None:
        return None

    pm._watch_pods = mock_watch  # type: ignore[method-assign]
    pm._reconciliation_loop = mock_reconcile  # type: ignore[method-assign]

    await pm.__aenter__()
    assert pm._watch_task is not None
    assert pm._reconcile_task is not None

    await pm.aclose()
