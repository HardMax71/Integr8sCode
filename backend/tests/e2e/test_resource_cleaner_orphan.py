import logging
from datetime import datetime

import pytest
from app.services.result_processor.resource_cleaner import ResourceCleaner
from app.settings import Settings
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config

pytestmark = [pytest.mark.e2e, pytest.mark.k8s]

_test_logger = logging.getLogger("test.k8s.resource_cleaner_orphan")


def _ensure_kubeconfig() -> None:
    try:
        k8s_config.load_incluster_config()
    except Exception:
        k8s_config.load_kube_config()


@pytest.mark.asyncio
async def test_cleanup_orphaned_configmaps_dry_run(test_settings: Settings) -> None:
    _ensure_kubeconfig()
    v1 = k8s_client.CoreV1Api()
    ns = test_settings.K8S_NAMESPACE
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
        # Force as orphaned by using a large cutoff - ConfigMap created synchronously, available now
        res = await cleaner.cleanup_orphaned_resources(namespace=ns, max_age_hours=0, dry_run=True)
        # ConfigMap should be detected immediately
        assert any(name == cm for cm in res.get("configmaps", [])), (
            f"Expected ConfigMap '{name}' to be detected as orphan candidate"
        )
    finally:
        # Cleanup resource
        try:
            v1.delete_namespaced_config_map(name=name, namespace=ns)
        except Exception:
            pass
