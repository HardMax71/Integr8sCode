import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pytest
from kubernetes import client as k8s_client, config as k8s_config

from app.services.result_processor.resource_cleaner import ResourceCleaner
from tests.helpers.eventually import eventually

pytestmark = [pytest.mark.integration, pytest.mark.k8s]

_test_logger = logging.getLogger("test.k8s.resource_cleaner_integration")


def _ensure_kubeconfig():
    try:
        k8s_config.load_incluster_config()
    except Exception:
        k8s_config.load_kube_config()


@pytest.mark.asyncio
async def test_cleanup_orphaned_configmaps_dry_run():
    _ensure_kubeconfig()
    v1 = k8s_client.CoreV1Api()
    ns = "default"
    name = f"int-test-cm-{int(datetime.now().timestamp())}"

    # Create a configmap labeled like the app uses
    metadata = k8s_client.V1ObjectMeta(
        name=name,
        labels={"app": "integr8s", "execution-id": "e-int-test"},
    )
    body = k8s_client.V1ConfigMap(metadata=metadata, data={"k": "v"})
    v1.create_namespaced_config_map(namespace=ns, body=body)

    try:
        cleaner = ResourceCleaner(logger=_test_logger)
        # Force as orphaned by using a large cutoff
        cleaned = await cleaner.cleanup_orphaned_resources(namespace=ns, max_age_hours=0, dry_run=True)

        # We expect our configmap to be a candidate; poll the response
        async def _has_cm():
            # If cleaner is non-deterministic across runs, re-invoke to reflect current state
            res = await cleaner.cleanup_orphaned_resources(namespace=ns, max_age_hours=0, dry_run=True)
            assert any(name == cm for cm in res.get("configmaps", []))

        await eventually(_has_cm, timeout=2.0, interval=0.1)
    finally:
        # Cleanup resource
        try:
            v1.delete_namespaced_config_map(name=name, namespace=ns)
        except Exception:
            pass
