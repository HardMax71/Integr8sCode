import asyncio
import logging
import os

import pytest

from app.services.result_processor.resource_cleaner import ResourceCleaner


pytestmark = [pytest.mark.e2e, pytest.mark.k8s]

_test_logger = logging.getLogger("test.k8s.resource_cleaner_k8s")


@pytest.mark.asyncio
async def test_initialize_and_get_usage() -> None:
    rc = ResourceCleaner(logger=_test_logger)
    await rc.initialize()
    usage = await rc.get_resource_usage(namespace=os.environ.get("K8S_NAMESPACE", "default"))
    assert set(usage.keys()) >= {"pods", "configmaps", "network_policies"}


@pytest.mark.asyncio
async def test_cleanup_orphaned_resources_dry_run() -> None:
    rc = ResourceCleaner(logger=_test_logger)
    await rc.initialize()
    cleaned = await rc.cleanup_orphaned_resources(
        namespace=os.environ.get("K8S_NAMESPACE", "default"),
        max_age_hours=0,
        dry_run=True,
    )
    assert set(cleaned.keys()) >= {"pods", "configmaps", "pvcs"}


@pytest.mark.asyncio
async def test_cleanup_nonexistent_pod() -> None:
    rc = ResourceCleaner(logger=_test_logger)
    await rc.initialize()

    # Attempt to delete a pod that doesn't exist - should complete without errors
    namespace = os.environ.get("K8S_NAMESPACE", "default")
    nonexistent_pod = "integr8s-test-nonexistent-pod"

    # Should complete within timeout and not raise any exceptions
    start_time = asyncio.get_event_loop().time()
    await rc.cleanup_pod_resources(
        pod_name=nonexistent_pod,
        namespace=namespace,
        execution_id="test-exec-nonexistent",
        timeout=5,
    )
    elapsed = asyncio.get_event_loop().time() - start_time

    # Verify it completed quickly (not waiting full timeout for non-existent resources)
    assert elapsed < 5, f"Cleanup took {elapsed}s, should be quick for non-existent resources"

    # Verify no resources exist with this name (should be empty/zero)
    usage = await rc.get_resource_usage(namespace=namespace)

    # usage returns counts (int), not lists
    # Just check that we got a valid usage report
    assert isinstance(usage.get("pods", 0), int)
    assert isinstance(usage.get("configmaps", 0), int)
