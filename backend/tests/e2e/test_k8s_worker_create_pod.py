import logging
import uuid

import pytest
from app.core.metrics import EventMetrics
from app.domain.events.typed import CreatePodCommandEvent, EventMetadata
from app.events.core import UnifiedProducer
from app.services.k8s_worker.config import K8sWorkerConfig
from app.services.k8s_worker.worker_logic import K8sWorkerLogic
from app.settings import Settings
from dishka import AsyncContainer
from kubernetes.client.rest import ApiException

pytestmark = [pytest.mark.e2e, pytest.mark.k8s]

_test_logger = logging.getLogger("test.k8s.worker_create_pod")


@pytest.mark.asyncio
async def test_worker_creates_configmap_and_pod(
        scope: AsyncContainer, test_settings: Settings
) -> None:
    ns = test_settings.K8S_NAMESPACE

    producer: UnifiedProducer = await scope.get(UnifiedProducer)
    event_metrics: EventMetrics = await scope.get(EventMetrics)

    cfg = K8sWorkerConfig(namespace=ns, max_concurrent_pods=1)
    logic = K8sWorkerLogic(
        config=cfg,
        producer=producer,
        settings=test_settings,
        logger=_test_logger,
        event_metrics=event_metrics,
    )

    # Initialize k8s clients using logic's own method
    try:
        logic.initialize()
    except RuntimeError as e:
        if "default" in str(e):
            pytest.skip("K8S_NAMESPACE is set to 'default', which is forbidden")
        raise

    if logic.v1 is None:
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
    cm = logic.pod_builder.build_config_map(
        command=cmd,
        script_content=cmd.script,
        entrypoint_content=await logic._get_entrypoint_script(),  # noqa: SLF001
    )
    try:
        await logic._create_config_map(cm)  # noqa: SLF001
    except ApiException as e:
        if e.status in (403, 404):
            pytest.skip(f"Insufficient permissions or namespace not found: {e}")
        raise

    pod = logic.pod_builder.build_pod_manifest(cmd)
    await logic._create_pod(pod)  # noqa: SLF001

    # Verify resources exist
    got_cm = logic.v1.read_namespaced_config_map(name=f"script-{exec_id}", namespace=ns)
    assert got_cm is not None
    got_pod = logic.v1.read_namespaced_pod(name=f"executor-{exec_id}", namespace=ns)
    assert got_pod is not None

    # Cleanup
    logic.v1.delete_namespaced_pod(name=f"executor-{exec_id}", namespace=ns)
    logic.v1.delete_namespaced_config_map(name=f"script-{exec_id}", namespace=ns)
