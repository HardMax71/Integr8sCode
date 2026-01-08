import logging
from datetime import datetime

import backoff
import pytest
from app.services.result_processor.resource_cleaner import ResourceCleaner
from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio import config as k8s_config

pytestmark = [pytest.mark.e2e, pytest.mark.k8s]

_test_logger = logging.getLogger("test.k8s.resource_cleaner_orphan")


async def _ensure_kubeconfig() -> k8s_client.ApiClient:
    """Load kubeconfig and return an async API client."""
    try:
        k8s_config.load_incluster_config()
    except Exception:
        await k8s_config.load_kube_config()
    return k8s_client.ApiClient()


@pytest.mark.asyncio
async def test_cleanup_orphaned_configmaps_dry_run() -> None:
    api_client = await _ensure_kubeconfig()
    name: str | None = None
    try:
        v1 = k8s_client.CoreV1Api(api_client)
        ns = "default"
        name = f"int-test-cm-{int(datetime.now().timestamp())}"

        # Create a configmap labeled like the app uses
        metadata = k8s_client.V1ObjectMeta(
            name=name,
            labels={"app": "integr8s", "execution-id": "e-int-test"},
        )
        body = k8s_client.V1ConfigMap(metadata=metadata, data={"k": "v"})
        await v1.create_namespaced_config_map(namespace=ns, body=body)

        cleaner = ResourceCleaner(logger=_test_logger)

        # We expect our configmap to be a candidate; poll the response
        @backoff.on_exception(backoff.constant, AssertionError, max_time=2.0, interval=0.1)
        async def _wait_has_cm() -> None:
            # If cleaner is non-deterministic across runs, re-invoke to reflect current state
            res = await cleaner.cleanup_orphaned_resources(namespace=ns, max_age_hours=0, dry_run=True)
            assert any(name == cm for cm in res.get("configmaps", []))

        await _wait_has_cm()
    finally:
        # Cleanup resource (only if created)
        if name:
            try:
                v1 = k8s_client.CoreV1Api(api_client)
                await v1.delete_namespaced_config_map(name=name, namespace="default")
            except Exception:
                pass
        await api_client.close()
