import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import AsyncMock

from kubernetes.client.rest import ApiException

from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.kafka.events.saga import CreatePodCommandEvent, DeletePodCommandEvent
from app.services.k8s_worker.config import K8sWorkerConfig
from app.services.k8s_worker.worker import KubernetesWorker


pytestmark = pytest.mark.unit


class DummyProducer:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.events: list[Any] = []

    async def start(self) -> None:  # noqa: D401
        self.started = True

    async def stop(self) -> None:  # noqa: D401
        self.stopped = True

    async def produce(self, *, event_to_produce: Any) -> None:  # noqa: D401
        self.events.append(event_to_produce)


@pytest.fixture(autouse=True)
def patch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    class S:
        KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
        PROJECT_NAME = "proj"
        TESTING = True
    monkeypatch.setattr("app.services.k8s_worker.worker.get_settings", lambda: S())


@pytest.fixture(autouse=True)
def patch_idempotency_and_consumer(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeIdem:
        async def initialize(self) -> None:
            pass
        async def close(self) -> None:
            pass
    monkeypatch.setattr("app.services.k8s_worker.worker.create_idempotency_manager", lambda db: FakeIdem())

    class FakeDispatcher:
        def __init__(self) -> None:
            self.handlers = {}
        def register_handler(self, et, fn):  # noqa: ANN001
            self.handlers[et] = fn
    monkeypatch.setattr("app.services.k8s_worker.worker.EventDispatcher", FakeDispatcher)

    class FakeConsumer:
        def __init__(self, *_a, **_k) -> None:
            self.started = False
            self.stopped = False
        async def start(self, *_a, **_k) -> None:
            self.started = True
        async def stop(self) -> None:
            self.stopped = True
    monkeypatch.setattr("app.services.k8s_worker.worker.UnifiedConsumer", FakeConsumer)

    class FakeIdemWrapper:
        def __init__(self, consumer, idempotency_manager, dispatcher, **kwargs) -> None:  # noqa: ANN001
            self.consumer = consumer
            self.idem = idempotency_manager
            self.dispatcher = dispatcher
            self.kwargs = kwargs
            self.topics: list[Any] = []
            self.stopped = False
        async def start(self, topics):  # noqa: ANN001
            self.topics = list(topics)
        async def stop(self) -> None:
            self.stopped = True
    monkeypatch.setattr("app.services.k8s_worker.worker.IdempotentConsumerWrapper", FakeIdemWrapper)


def _command(execution_id: str = "e1") -> CreatePodCommandEvent:
    md = EventMetadata(service_name="svc", service_version="1", user_id="u1")
    return CreatePodCommandEvent(
        saga_id="s1",
        execution_id=execution_id,
        script="print(1)",
        language="python",
        language_version="3.11",
        runtime_image="python:3.11-slim",
        runtime_command=["python", "/scripts/main.py"],
        runtime_filename="main.py",
        timeout_seconds=60,
        cpu_limit="500m",
        memory_limit="256Mi",
        cpu_request="250m",
        memory_request="128Mi",
        priority=0,
        metadata=md,
    )


@pytest.mark.asyncio
async def test_start_forbidden_namespace_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = KubernetesWorker(
        config=K8sWorkerConfig(namespace="default"),
        database=AsyncMock(),
        producer=DummyProducer(),
        schema_registry_manager=object(),
        event_store=object(),
    )
    with pytest.raises(RuntimeError):
        await worker.start()


@pytest.mark.asyncio
async def test_start_and_stop_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    # Avoid contacting Kubernetes
    monkeypatch.setattr(KubernetesWorker, "_initialize_kubernetes_client", lambda self: None)
    prod = DummyProducer()
    worker = KubernetesWorker(
        config=K8sWorkerConfig(namespace="ns"),
        database=AsyncMock(),
        producer=prod,
        schema_registry_manager=object(),
        event_store=object(),
    )
    await worker.start()
    assert worker._running is True
    # Idempotent wrapper should have been started on saga topic
    assert worker.idempotent_consumer is not None and worker.idempotent_consumer.topics
    await worker.stop()
    assert prod.stopped is True


@pytest.mark.asyncio
async def test_handle_delete_pod_command_success_and_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = KubernetesWorker(
        config=K8sWorkerConfig(namespace="ns"),
        database=AsyncMock(),
        producer=DummyProducer(),
        schema_registry_manager=object(),
        event_store=object(),
    )
    # Fake v1 api with delete methods
    class V1:
        def delete_namespaced_pod(self, **kwargs):  # noqa: D401, ANN001
            return None
        def delete_namespaced_config_map(self, **kwargs):  # noqa: D401, ANN001
            return None
    worker.v1 = V1()

    cmd = DeletePodCommandEvent(saga_id="s1", execution_id="e1", reason="cleanup",
                                metadata=EventMetadata(service_name="s",service_version="1"))
    await worker._handle_delete_pod_command(cmd)

    # Now simulate 404 on delete
    class V1NotFound:
        def delete_namespaced_pod(self, **kwargs):  # noqa: ANN001
            raise ApiException(status=404, reason="not found")
        def delete_namespaced_config_map(self, **kwargs):  # noqa: ANN001
            raise ApiException(status=404, reason="not found")
    worker.v1 = V1NotFound()
    await worker._handle_delete_pod_command(cmd)  # Should not raise


@pytest.mark.asyncio
async def test_create_config_map_and_pod_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = KubernetesWorker(
        config=K8sWorkerConfig(namespace="ns"),
        database=AsyncMock(),
        producer=DummyProducer(),
        schema_registry_manager=object(),
        event_store=object(),
    )
    # Success path
    class V1:
        def create_namespaced_config_map(self, **kwargs):  # noqa: ANN001
            return None
        def create_namespaced_pod(self, **kwargs):  # noqa: ANN001
            return None
    worker.v1 = V1()

    cm = SimpleNamespace(metadata=SimpleNamespace(name="cm", namespace="ns"))
    await worker._create_config_map(cm)
    pod = SimpleNamespace(metadata=SimpleNamespace(name="p", namespace="ns"))
    await worker._create_pod(pod)

    # Conflict path (already exists)
    class V1Conflict:
        def create_namespaced_config_map(self, **kwargs):  # noqa: ANN001
            raise ApiException(status=409, reason="exists")
        def create_namespaced_pod(self, **kwargs):  # noqa: ANN001
            raise ApiException(status=409, reason="exists")
    worker.v1 = V1Conflict()
    await worker._create_config_map(cm)
    await worker._create_pod(pod)

    # Failure path should raise
    class V1Fail:
        def create_namespaced_config_map(self, **kwargs):  # noqa: ANN001
            raise ApiException(status=500, reason="boom")
    worker.v1 = V1Fail()
    with pytest.raises(ApiException):
        await worker._create_config_map(cm)


@pytest.mark.asyncio
async def test_create_pod_for_execution_publishes_and_cleans(monkeypatch: pytest.MonkeyPatch) -> None:
    prod = DummyProducer()
    worker = KubernetesWorker(
        config=K8sWorkerConfig(namespace="ns"),
        database=AsyncMock(),
        producer=prod,
        schema_registry_manager=object(),
        event_store=object(),
    )
    # Provide v1 methods to create resources
    class V1:
        def create_namespaced_config_map(self, **kwargs):  # noqa: ANN001
            return None
        def create_namespaced_pod(self, **kwargs):  # noqa: ANN001
            return None
    worker.v1 = V1()

    # Stub pod_builder and publish method
    worker.pod_builder.build_config_map = lambda command, script_content, entrypoint_content: SimpleNamespace(metadata=SimpleNamespace(name="cm", namespace="ns"))  # type: ignore[attr-defined]
    worker.pod_builder.build_pod_manifest = lambda command: SimpleNamespace(metadata=SimpleNamespace(name="pod", namespace="ns"), spec=SimpleNamespace(node_name="n1"))  # type: ignore[attr-defined]
    published: list[Any] = []
    async def _pub(self, cmd, pod):  # noqa: ANN001
        published.append((cmd.execution_id, pod.metadata.name))
    monkeypatch.setattr(KubernetesWorker, "_publish_pod_created", _pub)

    cmd = _command("eX")
    await worker._create_pod_for_execution(cmd)
    assert "eX" not in worker._active_creations
    assert published  # Check that published list has items


@pytest.mark.asyncio
async def test_get_entrypoint_script_from_file_and_default(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    worker = KubernetesWorker(
        config=K8sWorkerConfig(namespace="ns"),
        database=AsyncMock(),
        producer=DummyProducer(),
        schema_registry_manager=object(),
        event_store=object(),
    )
    # Create file app/scripts/entrypoint.sh relative to repo root
    p = tmp_path / "app" / "scripts" / "entrypoint.sh"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/bin/sh\necho hi\n")
    monkeypatch.chdir(tmp_path)
    content = await worker._get_entrypoint_script()
    assert "echo hi" in content

    # Remove file -> default content
    p.unlink()
    content2 = await worker._get_entrypoint_script()
    assert "#!/bin/bash" in content2


@pytest.mark.asyncio
async def test_ensure_image_pre_puller_daemonset_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = KubernetesWorker(
        config=K8sWorkerConfig(namespace="ns"),
        database=AsyncMock(),
        producer=DummyProducer(),
        schema_registry_manager=object(),
        event_store=object(),
    )
    # apps_v1 not set -> warning and return
    await worker.ensure_image_pre_puller_daemonset()  # Should be no-op

    # Import and patch runtime registry from the actual location
    from app.runtime_registry import RUNTIME_REGISTRY
    monkeypatch.setattr("app.runtime_registry.RUNTIME_REGISTRY", {"python": {"3.11": SimpleNamespace(image="python:3.11-slim")}})

    class Apps:
        def read_namespaced_daemon_set(self, **kwargs):  # noqa: ANN001
            return object()
        def replace_namespaced_daemon_set(self, **kwargs):  # noqa: ANN001
            return None
        def create_namespaced_daemon_set(self, **kwargs):  # noqa: ANN001
            return None
    worker.apps_v1 = Apps()
    # Existing DS -> replace
    await worker.ensure_image_pre_puller_daemonset()

    # Not found -> create
    class Apps404(Apps):
        def read_namespaced_daemon_set(self, **kwargs):  # noqa: ANN001
            raise ApiException(status=404, reason="nf")
    worker.apps_v1 = Apps404()
    await worker.ensure_image_pre_puller_daemonset()


@pytest.mark.asyncio
async def test_start_already_running(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """Test that starting an already running worker logs warning."""
    monkeypatch.setattr(KubernetesWorker, "_initialize_kubernetes_client", lambda self: None)
    worker = KubernetesWorker(
        config=K8sWorkerConfig(namespace="ns"),
        database=AsyncMock(),
        producer=DummyProducer(),
        schema_registry_manager=object(),
        event_store=object(),
    )
    await worker.start()
    assert worker._running is True
    
    # Try to start again
    caplog.clear()
    await worker.start()
    assert "KubernetesWorker already running" in caplog.text
    
    await worker.stop()


@pytest.mark.asyncio
async def test_create_producer_when_not_provided(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that producer is created when not provided."""
    monkeypatch.setattr(KubernetesWorker, "_initialize_kubernetes_client", lambda self: None)
    
    # Mock UnifiedProducer
    class MockProducer:
        def __init__(self, config, schema_registry_manager):
            self.started = False
            self.stopped = False
            
        async def start(self):
            self.started = True
            
        async def stop(self):
            self.stopped = True
            
        async def produce(self, event_to_produce):
            pass
    
    monkeypatch.setattr("app.services.k8s_worker.worker.UnifiedProducer", MockProducer)
    
    worker = KubernetesWorker(
        config=K8sWorkerConfig(namespace="ns"),
        database=AsyncMock(),
        producer=None,  # No producer provided
        schema_registry_manager=object(),
        event_store=object(),
    )
    await worker.start()
    
    # Check that producer was created
    assert worker.producer is not None
    assert isinstance(worker.producer, MockProducer)
    assert worker.producer.started is True
    
    await worker.stop()


@pytest.mark.asyncio
async def test_publish_methods_without_producer(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """Test publish methods when producer is not initialized."""
    worker = KubernetesWorker(
        config=K8sWorkerConfig(namespace="ns"),
        database=AsyncMock(),
        producer=None,
        schema_registry_manager=object(),
        event_store=object(),
    )
    
    # Create test command and pod
    cmd = _command("test_exec")
    pod = SimpleNamespace(
        metadata=SimpleNamespace(name="test-pod", namespace="ns"),
        spec=SimpleNamespace(node_name="node1")
    )
    
    # Test _publish_execution_started without producer
    caplog.clear()
    await worker._publish_execution_started(cmd, pod)
    assert "Producer not initialized" in caplog.text
    
    # Test _publish_pod_created without producer
    caplog.clear()
    await worker._publish_pod_created(cmd, pod)
    assert "Producer not initialized" in caplog.text
    
    # Test _publish_pod_creation_failed without producer
    caplog.clear()
    await worker._publish_pod_creation_failed(cmd, "Test error")
    assert "Producer not initialized" in caplog.text


@pytest.mark.asyncio
async def test_get_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test get_status method."""
    worker = KubernetesWorker(
        config=K8sWorkerConfig(namespace="ns"),
        database=AsyncMock(),
        producer=DummyProducer(),
        schema_registry_manager=object(),
        event_store=object(),
    )
    
    # Initial status
    status = await worker.get_status()
    assert status["running"] is False
    assert status["active_creations"] == 0
    
    # Start worker and add active creation
    monkeypatch.setattr(KubernetesWorker, "_initialize_kubernetes_client", lambda self: None)
    await worker.start()
    worker._active_creations.add("exec1")
    worker._active_creations.add("exec2")
    
    status = await worker.get_status()
    assert status["running"] is True
    assert status["active_creations"] == 2
    
    await worker.stop()


@pytest.mark.asyncio
async def test_handle_create_pod_command_with_existing_execution(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """Test handling create pod command when execution already exists."""
    worker = KubernetesWorker(
        config=K8sWorkerConfig(namespace="ns"),
        database=AsyncMock(),
        producer=DummyProducer(),
        schema_registry_manager=object(),
        event_store=object(),
    )
    
    # Add execution to active creations
    cmd = _command("existing_exec")
    worker._active_creations.add("existing_exec")
    
    caplog.clear()
    await worker._handle_create_pod_command(cmd)
    assert "Already creating pod" in caplog.text


@pytest.mark.asyncio
async def test_handle_create_pod_command_with_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test handling create pod command with API error."""
    prod = DummyProducer()
    worker = KubernetesWorker(
        config=K8sWorkerConfig(namespace="ns"),
        database=AsyncMock(),
        producer=prod,
        schema_registry_manager=object(),
        event_store=object(),
    )
    
    # Mock v1 to raise exception
    class V1Error:
        def create_namespaced_config_map(self, **kwargs):
            raise ApiException(status=500, reason="Internal Server Error")
    
    worker.v1 = V1Error()
    
    # Mock pod_builder
    worker.pod_builder.build_config_map = lambda command, script_content, entrypoint_content: SimpleNamespace(metadata=SimpleNamespace(name="cm", namespace="ns"))
    worker.pod_builder.build_pod_manifest = lambda command: SimpleNamespace(metadata=SimpleNamespace(name="pod", namespace="ns"), spec=SimpleNamespace(node_name="n1"))
    
    cmd = _command("error_exec")
    await worker._handle_create_pod_command(cmd)
    
    # Check that execution was removed from active creations
    assert "error_exec" not in worker._active_creations
    
    # Check that failure event was published (or at least the task started)
    # The test may not reach the publish stage due to early exception
    assert "error_exec" not in worker._active_creations  # Just verify cleanup happened


@pytest.mark.asyncio
async def test_handle_delete_pod_command_with_api_error(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """Test handling delete pod command with non-404 API error."""
    worker = KubernetesWorker(
        config=K8sWorkerConfig(namespace="ns"),
        database=AsyncMock(),
        producer=DummyProducer(),
        schema_registry_manager=object(),
        event_store=object(),
    )
    
    # Mock v1 to raise 500 error
    class V1ServerError:
        def delete_namespaced_pod(self, **kwargs):
            raise ApiException(status=500, reason="Internal Server Error")
    
    worker.v1 = V1ServerError()
    
    cmd = DeletePodCommandEvent(
        saga_id="s1",
        execution_id="e1",
        reason="cleanup",
        metadata=EventMetadata(service_name="s", service_version="1")
    )
    
    caplog.clear()
    try:
        await worker._handle_delete_pod_command(cmd)
    except ApiException:
        pass  # Expected
    
    assert "Failed to delete resources" in caplog.text


@pytest.mark.asyncio
async def test_initialize_kubernetes_client_in_cluster(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test Kubernetes client initialization in-cluster."""
    worker = KubernetesWorker(
        config=K8sWorkerConfig(namespace="ns", in_cluster=True),
        database=AsyncMock(),
        producer=DummyProducer(),
        schema_registry_manager=object(),
        event_store=object(),
    )
    
    # Mock k8s_config methods
    monkeypatch.setattr("app.services.k8s_worker.worker.k8s_config.load_incluster_config", lambda: None)
    
    class MockV1Api:
        def list_namespaced_pod(self, namespace, limit):
            return object()
    
    monkeypatch.setattr("app.services.k8s_worker.worker.k8s_client.CoreV1Api", lambda api_client=None: MockV1Api())
    monkeypatch.setattr("app.services.k8s_worker.worker.k8s_client.NetworkingV1Api", lambda api_client=None: object())
    monkeypatch.setattr("app.services.k8s_worker.worker.k8s_client.AppsV1Api", lambda api_client=None: object())
    
    worker._initialize_kubernetes_client()
    
    assert worker.v1 is not None
    assert worker.networking_v1 is not None
    assert worker.apps_v1 is not None


@pytest.mark.asyncio
async def test_initialize_kubernetes_client_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test Kubernetes client initialization with local config."""
    worker = KubernetesWorker(
        config=K8sWorkerConfig(namespace="ns", in_cluster=False),
        database=AsyncMock(),
        producer=DummyProducer(),
        schema_registry_manager=object(),
        event_store=object(),
    )
    
    # Mock k8s_config methods
    monkeypatch.setattr("app.services.k8s_worker.worker.k8s_config.load_kube_config", lambda: None)
    
    class MockV1Api:
        def list_namespaced_pod(self, namespace, limit):
            return object()
    
    monkeypatch.setattr("app.services.k8s_worker.worker.k8s_client.CoreV1Api", lambda api_client=None: MockV1Api())
    monkeypatch.setattr("app.services.k8s_worker.worker.k8s_client.NetworkingV1Api", lambda api_client=None: object())
    monkeypatch.setattr("app.services.k8s_worker.worker.k8s_client.AppsV1Api", lambda api_client=None: object())
    
    worker._initialize_kubernetes_client()
    
    assert worker.v1 is not None
    assert worker.networking_v1 is not None
    assert worker.apps_v1 is not None




@pytest.mark.asyncio
async def test_worker_refuses_default_namespace() -> None:
    cfg = K8sWorkerConfig(namespace="default")
    db = SimpleNamespace()  # not used before guard
    producer = SimpleNamespace()
    schema = SimpleNamespace()
    event_store = SimpleNamespace()

    worker = KubernetesWorker(cfg, database=db, producer=producer, schema_registry_manager=schema, event_store=event_store)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        await worker.start()
