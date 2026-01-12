import logging
import os
import uuid

import pytest
from app.domain.events.typed import CreatePodCommandEvent, EventMetadata
from app.events.core import UnifiedProducer
from app.events.event_store import EventStore
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.idempotency import IdempotencyManager
from app.services.k8s_worker.config import K8sWorkerConfig
from app.services.k8s_worker.worker import KubernetesWorker
from app.settings import Settings
from dishka import AsyncContainer
from kubernetes.client.rest import ApiException

pytestmark = [pytest.mark.e2e, pytest.mark.k8s]

_test_logger = logging.getLogger("test.k8s.worker_create_pod")


@pytest.mark.asyncio
async def test_worker_creates_configmap_and_pod(
    scope: AsyncContainer, monkeypatch: pytest.MonkeyPatch, test_settings: Settings
) -> None:
    # Ensure non-default namespace for worker validation
    ns = os.environ.get("K8S_NAMESPACE", "integr8scode")
    if ns == "default":
        ns = "integr8scode"
        monkeypatch.setenv("K8S_NAMESPACE", ns)

    schema: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    store: EventStore = await scope.get(EventStore)
    producer: UnifiedProducer = await scope.get(UnifiedProducer)
    idem: IdempotencyManager = await scope.get(IdempotencyManager)

    cfg = K8sWorkerConfig(namespace=ns, max_concurrent_pods=1)
    worker = KubernetesWorker(
        config=cfg,
        producer=producer,
        schema_registry_manager=schema,
        settings=test_settings,
        event_store=store,
        idempotency_manager=idem,
        logger=_test_logger,
    )

    # Initialize k8s clients using worker's own method
    worker._initialize_kubernetes_client()  # noqa: SLF001
    if worker.v1 is None:
        pytest.skip("Kubernetes cluster not available")

    exec_id = uuid.uuid4().hex[:8]
    cmd = CreatePodCommandEvent(
        saga_id=uuid.uuid4().hex,
        execution_id=exec_id,
        script="echo hi",
        language="python",
        language_version="3.11",
        runtime_image="busybox:1.36",
        runtime_command=["echo", "done"],
        runtime_filename="main.py",
        timeout_seconds=60,
        cpu_limit="100m",
        memory_limit="128Mi",
        cpu_request="50m",
        memory_request="64Mi",
        priority=5,
        metadata=EventMetadata(service_name="tests", service_version="1", user_id="u1"),
    )

    # Build and create ConfigMap + Pod
    cm = worker.pod_builder.build_config_map(
        command=cmd,
        script_content=cmd.script,
        entrypoint_content=await worker._get_entrypoint_script(),  # noqa: SLF001
    )
    try:
        await worker._create_config_map(cm)  # noqa: SLF001
    except ApiException as e:
        if e.status in (403, 404):
            pytest.skip(f"Insufficient permissions or namespace not found: {e}")
        raise

    pod = worker.pod_builder.build_pod_manifest(cmd)
    await worker._create_pod(pod)  # noqa: SLF001

    # Verify resources exist
    got_cm = worker.v1.read_namespaced_config_map(name=f"script-{exec_id}", namespace=ns)
    assert got_cm is not None
    got_pod = worker.v1.read_namespaced_pod(name=f"executor-{exec_id}", namespace=ns)
    assert got_pod is not None

    # Cleanup
    worker.v1.delete_namespaced_pod(name=f"executor-{exec_id}", namespace=ns)
    worker.v1.delete_namespaced_config_map(name=f"script-{exec_id}", namespace=ns)
