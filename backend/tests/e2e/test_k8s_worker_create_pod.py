import logging
import uuid

import pytest
from app.domain.enums.execution import QueuePriority
from app.domain.events.typed import CreatePodCommandEvent, EventMetadata
from app.services.k8s_worker.worker import KubernetesWorker
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

    # Get worker from DI (already configured with dependencies)
    worker: KubernetesWorker = await scope.get(KubernetesWorker)

    if worker._v1 is None:  # noqa: SLF001
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
        priority=QueuePriority.NORMAL,
        metadata=EventMetadata(service_name="tests", service_version="1", user_id="u1"),
    )

    # Build and create ConfigMap + Pod
    cm = worker._pod_builder.build_config_map(  # noqa: SLF001
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

    pod = worker._pod_builder.build_pod_manifest(cmd)  # noqa: SLF001
    await worker._create_pod(pod)  # noqa: SLF001

    # Verify resources exist
    got_cm = worker._v1.read_namespaced_config_map(name=f"script-{exec_id}", namespace=ns)  # noqa: SLF001
    assert got_cm is not None
    got_pod = worker._v1.read_namespaced_pod(name=f"executor-{exec_id}", namespace=ns)  # noqa: SLF001
    assert got_pod is not None

    # Cleanup
    worker._v1.delete_namespaced_pod(name=f"executor-{exec_id}", namespace=ns)  # noqa: SLF001
    worker._v1.delete_namespaced_config_map(name=f"script-{exec_id}", namespace=ns)  # noqa: SLF001
