import asyncio
from datetime import datetime

import pytest
import pytest_asyncio
from app.core.k8s_clients import K8sClients
from app.services.result_processor.resource_cleaner import ResourceCleaner
from app.settings import Settings
from dishka import AsyncContainer
from kubernetes import client as k8s_client

pytestmark = [pytest.mark.e2e, pytest.mark.k8s]


@pytest_asyncio.fixture
async def k8s_clients(scope: AsyncContainer) -> K8sClients:
    """Get K8sClients from DI container."""
    return await scope.get(K8sClients)


@pytest_asyncio.fixture
async def resource_cleaner(scope: AsyncContainer) -> ResourceCleaner:
    """Get ResourceCleaner from DI container."""
    return await scope.get(ResourceCleaner)


@pytest.mark.asyncio
async def test_get_resource_usage(
    resource_cleaner: ResourceCleaner, test_settings: Settings
) -> None:
    usage = await resource_cleaner.get_resource_usage(namespace=test_settings.K8S_NAMESPACE)
    assert set(usage.keys()) >= {"pods", "configmaps", "network_policies"}


@pytest.mark.asyncio
async def test_cleanup_orphaned_resources_dry_run(
    resource_cleaner: ResourceCleaner, test_settings: Settings
) -> None:
    cleaned = await resource_cleaner.cleanup_orphaned_resources(
        namespace=test_settings.K8S_NAMESPACE,
        max_age_hours=0,
        dry_run=True,
    )
    assert set(cleaned.keys()) >= {"pods", "configmaps", "pvcs"}


@pytest.mark.asyncio
async def test_cleanup_nonexistent_pod(
    resource_cleaner: ResourceCleaner, test_settings: Settings
) -> None:
    namespace = test_settings.K8S_NAMESPACE
    nonexistent_pod = "integr8s-test-nonexistent-pod"

    start_time = asyncio.get_running_loop().time()
    await resource_cleaner.cleanup_pod_resources(
        pod_name=nonexistent_pod,
        namespace=namespace,
        execution_id="test-exec-nonexistent",
        timeout=5,
    )
    elapsed = asyncio.get_running_loop().time() - start_time

    assert elapsed < 5, f"Cleanup took {elapsed}s, should be quick for non-existent resources"

    usage = await resource_cleaner.get_resource_usage(namespace=namespace)
    assert isinstance(usage.get("pods", 0), int)
    assert isinstance(usage.get("configmaps", 0), int)


@pytest.mark.asyncio
async def test_cleanup_orphaned_configmaps_dry_run(
    k8s_clients: K8sClients, resource_cleaner: ResourceCleaner, test_settings: Settings
) -> None:
    v1 = k8s_clients.v1
    ns = test_settings.K8S_NAMESPACE
    name = f"int-test-cm-{int(datetime.now().timestamp())}"

    metadata = k8s_client.V1ObjectMeta(
        name=name,
        labels={"app": "integr8s", "execution-id": "e-int-test"},
    )
    body = k8s_client.V1ConfigMap(metadata=metadata, data={"k": "v"})
    v1.create_namespaced_config_map(namespace=ns, body=body)

    try:
        res = await resource_cleaner.cleanup_orphaned_resources(namespace=ns, max_age_hours=0, dry_run=True)
        assert any(name == cm for cm in res.get("configmaps", [])), (
            f"Expected ConfigMap '{name}' to be detected as orphan candidate"
        )
    finally:
        try:
            v1.delete_namespaced_config_map(name=name, namespace=ns)
        except Exception:
            pass
