import asyncio
from datetime import datetime

import pytest
from app.services.result_processor.resource_cleaner import ResourceCleaner
from app.settings import Settings
from dishka import AsyncContainer
from kubernetes_asyncio import client as k8s_client

pytestmark = [pytest.mark.e2e, pytest.mark.k8s]


@pytest.mark.asyncio
async def test_get_resource_usage(scope: AsyncContainer, test_settings: Settings) -> None:
    resource_cleaner = await scope.get(ResourceCleaner)
    usage = await resource_cleaner.get_resource_usage(namespace=test_settings.K8S_NAMESPACE)
    assert set(usage.keys()) >= {"pods", "configmaps", "network_policies"}


@pytest.mark.asyncio
async def test_cleanup_orphaned_resources_dry_run(scope: AsyncContainer, test_settings: Settings) -> None:
    resource_cleaner = await scope.get(ResourceCleaner)
    cleaned = await resource_cleaner.cleanup_orphaned_resources(
        namespace=test_settings.K8S_NAMESPACE,
        max_age_hours=0,
        dry_run=True,
    )
    assert set(cleaned.keys()) >= {"pods", "configmaps", "pvcs"}


@pytest.mark.asyncio
async def test_cleanup_nonexistent_pod(scope: AsyncContainer, test_settings: Settings) -> None:
    resource_cleaner = await scope.get(ResourceCleaner)
    namespace = test_settings.K8S_NAMESPACE
    nonexistent_pod = "integr8s-test-nonexistent-pod"

    # Use a local timeout variable with buffer for scheduler jitter
    timeout = 2  # Reduced from 5s since non-existent resources return immediately (404)
    jitter_buffer = 0.5  # Account for scheduler/GC pauses

    start_time = asyncio.get_running_loop().time()
    await resource_cleaner.cleanup_pod_resources(
        pod_name=nonexistent_pod,
        namespace=namespace,
        execution_id="test-exec-nonexistent",
        timeout=timeout,
    )
    elapsed = asyncio.get_running_loop().time() - start_time

    assert elapsed < timeout + jitter_buffer, (
        f"Cleanup took {elapsed:.2f}s, expected < {timeout + jitter_buffer}s for non-existent resources"
    )

    usage = await resource_cleaner.get_resource_usage(namespace=namespace)
    assert isinstance(usage.get("pods", 0), int)
    assert isinstance(usage.get("configmaps", 0), int)


@pytest.mark.asyncio
async def test_cleanup_orphaned_configmaps_dry_run(scope: AsyncContainer, test_settings: Settings) -> None:
    api_client = await scope.get(k8s_client.ApiClient)
    resource_cleaner = await scope.get(ResourceCleaner)

    v1 = k8s_client.CoreV1Api(api_client)
    ns = test_settings.K8S_NAMESPACE
    name = f"int-test-cm-{int(datetime.now().timestamp())}"

    metadata = k8s_client.V1ObjectMeta(
        name=name,
        labels={"app": "integr8s", "execution-id": "e-int-test"},
    )
    body = k8s_client.V1ConfigMap(metadata=metadata, data={"k": "v"})
    await v1.create_namespaced_config_map(namespace=ns, body=body)

    try:
        res = await resource_cleaner.cleanup_orphaned_resources(namespace=ns, max_age_hours=0, dry_run=True)
        assert any(name == cm for cm in res.get("configmaps", [])), (
            f"Expected ConfigMap '{name}' to be detected as orphan candidate"
        )
    finally:
        try:
            await v1.delete_namespaced_config_map(name=name, namespace=ns)
        except Exception:
            pass
