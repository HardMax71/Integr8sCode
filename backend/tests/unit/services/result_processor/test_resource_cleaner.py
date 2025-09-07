import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from kubernetes.client.rest import ApiException

from app.core.exceptions import ServiceError
from app.services.result_processor.resource_cleaner import ResourceCleaner


class FakeV1:
    def __init__(self):
        self.deleted = []
        # For list calls return objects with items having metadata
        self._pods = []
        self._cms = []
        self._pvcs = []

    # Read/Delete Pod
    def read_namespaced_pod(self, name, namespace):  # noqa: ANN001
        return SimpleNamespace()
    def delete_namespaced_pod(self, name, namespace, grace_period_seconds=30):  # noqa: ANN001
        self.deleted.append(("pod", name))
    # ConfigMaps
    def list_namespaced_config_map(self, namespace, label_selector=None):  # noqa: ANN001
        return SimpleNamespace(items=self._cms)
    def delete_namespaced_config_map(self, name, namespace):  # noqa: ANN001
        self.deleted.append(("cm", name))
    # PVCs
    def list_namespaced_persistent_volume_claim(self, namespace, label_selector=None):  # noqa: ANN001
        return SimpleNamespace(items=self._pvcs)
    def delete_namespaced_persistent_volume_claim(self, name, namespace):  # noqa: ANN001
        self.deleted.append(("pvc", name))
    # Pods list
    def list_namespaced_pod(self, namespace, label_selector=None):  # noqa: ANN001
        return SimpleNamespace(items=self._pods)


class FakeNet:
    def list_namespaced_network_policy(self, namespace, label_selector=None):  # noqa: ANN001
        return SimpleNamespace(items=[SimpleNamespace(metadata=SimpleNamespace(name="np1"))])


@pytest.mark.asyncio
async def test_initialize_and_cleanup_pod_resources(monkeypatch):
    rc = ResourceCleaner()
    # Patch k8s_config to avoid real kube calls and set v1/net clients
    import app.services.result_processor.resource_cleaner as rcmod
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", lambda: None)
    monkeypatch.setattr(rcmod.k8s_config, "load_kube_config", lambda: None)
    fake_v1 = FakeV1()
    fake_net = FakeNet()
    monkeypatch.setattr(rcmod.k8s_client, "CoreV1Api", lambda: fake_v1)
    monkeypatch.setattr(rcmod.k8s_client, "NetworkingV1Api", lambda: fake_net)

    await rc.initialize()
    # Prepare list responses
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    cm = SimpleNamespace(metadata=SimpleNamespace(name="cm-x", creation_timestamp=old))
    pvc = SimpleNamespace(metadata=SimpleNamespace(name="pvc-x"))
    fake_v1._cms = [cm]
    fake_v1._pvcs = [pvc]

    await rc.cleanup_pod_resources(pod_name="p1", namespace="ns", execution_id="e1", timeout=1, delete_pvcs=True)
    assert ("pod", "p1") in fake_v1.deleted
    assert ("cm", "cm-x") in fake_v1.deleted
    assert ("pvc", "pvc-x") in fake_v1.deleted


@pytest.mark.asyncio
async def test_cleanup_orphaned_resources_dry_run(monkeypatch):
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", lambda: None)
    monkeypatch.setattr(rcmod.k8s_config, "load_kube_config", lambda: None)
    fake_v1 = FakeV1()
    monkeypatch.setattr(rcmod.k8s_client, "CoreV1Api", lambda: fake_v1)
    monkeypatch.setattr(rcmod.k8s_client, "NetworkingV1Api", lambda: FakeNet())

    await rc.initialize()
    # Create old pod and configmap entries
    old = datetime.now(timezone.utc) - timedelta(hours=48)
    pod = SimpleNamespace(metadata=SimpleNamespace(name="pod-old", creation_timestamp=old), status=SimpleNamespace(phase="Succeeded"))
    cm = SimpleNamespace(metadata=SimpleNamespace(name="cm-old", creation_timestamp=old))
    fake_v1._pods = [pod]
    fake_v1._cms = [cm]

    cleaned = await rc.cleanup_orphaned_resources(namespace="ns", max_age_hours=24, dry_run=True)
    assert "pod-old" in cleaned["pods"]
    assert "cm-old" in cleaned["configmaps"]


@pytest.mark.asyncio
async def test_get_resource_usage_counts(monkeypatch):
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", lambda: None)
    monkeypatch.setattr(rcmod.k8s_config, "load_kube_config", lambda: None)
    fake_v1 = FakeV1()
    fake_net = FakeNet()
    # Provide some items
    fake_v1._pods = [SimpleNamespace(metadata=SimpleNamespace(name="p"))]
    fake_v1._cms = [SimpleNamespace(metadata=SimpleNamespace(name="c"))]
    monkeypatch.setattr(rcmod.k8s_client, "CoreV1Api", lambda: fake_v1)
    monkeypatch.setattr(rcmod.k8s_client, "NetworkingV1Api", lambda: fake_net)

    await rc.initialize()
    counts = await rc.get_resource_usage(namespace="ns")
    assert counts["pods"] == 1
    assert counts["configmaps"] == 1
    assert "network_policies" in counts


@pytest.mark.asyncio
async def test_initialize_already_initialized(monkeypatch):
    """Test that initialize returns early if already initialized."""
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", lambda: None)
    monkeypatch.setattr(rcmod.k8s_client, "CoreV1Api", lambda: FakeV1())
    monkeypatch.setattr(rcmod.k8s_client, "NetworkingV1Api", lambda: FakeNet())
    
    await rc.initialize()
    assert rc._initialized is True
    
    # Call again - should return early
    await rc.initialize()
    assert rc._initialized is True


@pytest.mark.asyncio
async def test_initialize_incluster_config_exception(monkeypatch):
    """Test fallback to kubeconfig when incluster config fails."""
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    
    # Make load_incluster_config raise an exception
    def raise_config_exception():
        raise rcmod.k8s_config.ConfigException("Not in cluster")
    
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", raise_config_exception)
    monkeypatch.setattr(rcmod.k8s_config, "load_kube_config", lambda: None)
    monkeypatch.setattr(rcmod.k8s_client, "CoreV1Api", lambda: FakeV1())
    monkeypatch.setattr(rcmod.k8s_client, "NetworkingV1Api", lambda: FakeNet())
    
    await rc.initialize()
    assert rc._initialized is True


@pytest.mark.asyncio
async def test_initialize_complete_failure(monkeypatch):
    """Test that initialization failure raises ServiceError."""
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    
    # Make both config methods fail
    def raise_exception():
        raise Exception("Config failed")
    
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", raise_exception)
    monkeypatch.setattr(rcmod.k8s_config, "load_kube_config", raise_exception)
    
    with pytest.raises(ServiceError, match="Kubernetes initialization failed"):
        await rc.initialize()


@pytest.mark.asyncio
async def test_cleanup_pod_resources_timeout(monkeypatch):
    """Test timeout handling in cleanup_pod_resources."""
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", lambda: None)
    monkeypatch.setattr(rcmod.k8s_client, "CoreV1Api", lambda: FakeV1())
    monkeypatch.setattr(rcmod.k8s_client, "NetworkingV1Api", lambda: FakeNet())
    
    await rc.initialize()
    
    # Mock _delete_pod to take too long
    async def slow_delete(pod_name, namespace):
        await asyncio.sleep(10)
    
    monkeypatch.setattr(rc, "_delete_pod", slow_delete)
    
    with pytest.raises(ServiceError, match="Resource cleanup timed out"):
        await rc.cleanup_pod_resources(
            pod_name="test-pod",
            namespace="ns",
            timeout=0.1
        )


@pytest.mark.asyncio
async def test_cleanup_pod_resources_general_exception(monkeypatch):
    """Test that cleanup continues even when _delete_pod fails (due to return_exceptions=True)."""
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", lambda: None)
    monkeypatch.setattr(rcmod.k8s_client, "CoreV1Api", lambda: FakeV1())
    monkeypatch.setattr(rcmod.k8s_client, "NetworkingV1Api", lambda: FakeNet())
    
    await rc.initialize()
    
    # Mock _delete_pod to raise an exception
    async def failing_delete(pod_name, namespace):
        raise Exception("Delete failed")
    
    monkeypatch.setattr(rc, "_delete_pod", failing_delete)
    
    # Should complete without raising (due to return_exceptions=True in gather)
    await rc.cleanup_pod_resources(
        pod_name="test-pod",
        namespace="ns"
    )


@pytest.mark.asyncio
async def test_delete_pod_not_initialized():
    """Test _delete_pod raises error when not initialized."""
    rc = ResourceCleaner()
    
    with pytest.raises(ServiceError, match="Kubernetes client not initialized"):
        await rc._delete_pod("test-pod", "ns")


@pytest.mark.asyncio
async def test_delete_pod_already_deleted(monkeypatch):
    """Test _delete_pod handles 404 gracefully."""
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", lambda: None)
    
    class FakeV1WithApiException:
        def read_namespaced_pod(self, name, namespace):
            raise ApiException(status=404, reason="Not Found")
        
        def delete_namespaced_pod(self, name, namespace, grace_period_seconds=30):
            pass
    
    monkeypatch.setattr(rcmod.k8s_client, "CoreV1Api", FakeV1WithApiException)
    monkeypatch.setattr(rcmod.k8s_client, "NetworkingV1Api", lambda: FakeNet())
    
    await rc.initialize()
    
    # Should not raise, just log
    await rc._delete_pod("missing-pod", "ns")


@pytest.mark.asyncio
async def test_delete_pod_api_exception(monkeypatch):
    """Test _delete_pod re-raises non-404 API exceptions."""
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", lambda: None)
    
    class FakeV1WithApiException:
        def read_namespaced_pod(self, name, namespace):
            raise ApiException(status=500, reason="Server Error")
    
    monkeypatch.setattr(rcmod.k8s_client, "CoreV1Api", FakeV1WithApiException)
    monkeypatch.setattr(rcmod.k8s_client, "NetworkingV1Api", lambda: FakeNet())
    
    await rc.initialize()
    
    with pytest.raises(ApiException):
        await rc._delete_pod("test-pod", "ns")


@pytest.mark.asyncio
async def test_delete_configmaps_not_initialized():
    """Test _delete_configmaps raises error when not initialized."""
    rc = ResourceCleaner()
    
    with pytest.raises(ServiceError, match="Kubernetes client not initialized"):
        await rc._delete_configmaps("exec-123", "ns")


@pytest.mark.asyncio
async def test_delete_pvcs(monkeypatch):
    """Test _delete_pvcs method."""
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", lambda: None)
    
    fake_v1 = FakeV1()
    pvc = SimpleNamespace(metadata=SimpleNamespace(name="pvc-exec-123"))
    fake_v1._pvcs = [pvc]
    
    monkeypatch.setattr(rcmod.k8s_client, "CoreV1Api", lambda: fake_v1)
    monkeypatch.setattr(rcmod.k8s_client, "NetworkingV1Api", lambda: FakeNet())
    
    await rc.initialize()
    await rc._delete_pvcs("exec-123", "ns")
    
    assert ("pvc", "pvc-exec-123") in fake_v1.deleted


@pytest.mark.asyncio
async def test_delete_pvcs_not_initialized():
    """Test _delete_pvcs raises error when not initialized."""
    rc = ResourceCleaner()
    
    with pytest.raises(ServiceError, match="Kubernetes client not initialized"):
        await rc._delete_pvcs("exec-123", "ns")


@pytest.mark.asyncio
async def test_delete_labeled_resources_api_exception(monkeypatch, caplog):
    """Test _delete_labeled_resources handles API exceptions."""
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", lambda: None)
    monkeypatch.setattr(rcmod.k8s_client, "CoreV1Api", lambda: FakeV1())
    monkeypatch.setattr(rcmod.k8s_client, "NetworkingV1Api", lambda: FakeNet())
    
    await rc.initialize()
    
    # Mock the list function to raise ApiException
    def list_with_exception(namespace, label_selector=None):
        raise ApiException(status=500, reason="Server Error")
    
    # Should log error but not raise
    await rc._delete_labeled_resources(
        "exec-123",
        "ns",
        list_with_exception,
        rc.v1.delete_namespaced_config_map,
        "ConfigMap"
    )
    
    # Verify error was logged
    assert "Failed to delete ConfigMaps" in caplog.text


@pytest.mark.asyncio
async def test_cleanup_orphaned_resources_exception(monkeypatch):
    """Test cleanup_orphaned_resources exception handling."""
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", lambda: None)
    monkeypatch.setattr(rcmod.k8s_client, "CoreV1Api", lambda: FakeV1())
    monkeypatch.setattr(rcmod.k8s_client, "NetworkingV1Api", lambda: FakeNet())
    
    await rc.initialize()
    
    # Mock _cleanup_orphaned_pods to raise an exception
    async def failing_cleanup(*args):
        raise Exception("Cleanup failed")
    
    monkeypatch.setattr(rc, "_cleanup_orphaned_pods", failing_cleanup)
    
    with pytest.raises(ServiceError, match="Orphaned resource cleanup failed"):
        await rc.cleanup_orphaned_resources()


@pytest.mark.asyncio
async def test_cleanup_orphaned_pods_not_initialized():
    """Test _cleanup_orphaned_pods raises error when not initialized."""
    rc = ResourceCleaner()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    cleaned = {"pods": [], "configmaps": [], "pvcs": []}
    
    with pytest.raises(ServiceError, match="Kubernetes client not initialized"):
        await rc._cleanup_orphaned_pods("ns", cutoff, cleaned, dry_run=False)


@pytest.mark.asyncio
async def test_cleanup_orphaned_pods_with_deletion_error(monkeypatch):
    """Test _cleanup_orphaned_pods handles deletion errors gracefully."""
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", lambda: None)
    
    fake_v1 = FakeV1()
    old = datetime.now(timezone.utc) - timedelta(hours=48)
    pod = SimpleNamespace(
        metadata=SimpleNamespace(name="old-pod", creation_timestamp=old),
        status=SimpleNamespace(phase="Failed")
    )
    fake_v1._pods = [pod]
    
    monkeypatch.setattr(rcmod.k8s_client, "CoreV1Api", lambda: fake_v1)
    monkeypatch.setattr(rcmod.k8s_client, "NetworkingV1Api", lambda: FakeNet())
    
    await rc.initialize()
    
    # Mock _delete_pod to raise an exception
    async def failing_delete(pod_name, namespace):
        raise Exception("Delete failed")
    
    monkeypatch.setattr(rc, "_delete_pod", failing_delete)
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    cleaned = {"pods": [], "configmaps": [], "pvcs": []}
    
    # Should not raise, just log error
    await rc._cleanup_orphaned_pods("ns", cutoff, cleaned, dry_run=False)
    
    # Pod should still be marked as cleaned
    assert "old-pod" in cleaned["pods"]


@pytest.mark.asyncio
async def test_cleanup_orphaned_configmaps_not_initialized():
    """Test _cleanup_orphaned_configmaps raises error when not initialized."""
    rc = ResourceCleaner()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    cleaned = {"pods": [], "configmaps": [], "pvcs": []}
    
    with pytest.raises(ServiceError, match="Kubernetes client not initialized"):
        await rc._cleanup_orphaned_configmaps("ns", cutoff, cleaned, dry_run=False)


@pytest.mark.asyncio
async def test_cleanup_orphaned_configmaps_with_deletion_error(monkeypatch):
    """Test _cleanup_orphaned_configmaps handles deletion errors gracefully."""
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", lambda: None)
    
    fake_v1 = FakeV1()
    old = datetime.now(timezone.utc) - timedelta(hours=48)
    cm = SimpleNamespace(metadata=SimpleNamespace(name="old-cm", creation_timestamp=old))
    fake_v1._cms = [cm]
    
    # Make delete raise an exception
    def failing_delete_cm(name, namespace):
        raise Exception("Delete failed")
    fake_v1.delete_namespaced_config_map = failing_delete_cm
    
    monkeypatch.setattr(rcmod.k8s_client, "CoreV1Api", lambda: fake_v1)
    monkeypatch.setattr(rcmod.k8s_client, "NetworkingV1Api", lambda: FakeNet())
    
    await rc.initialize()
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    cleaned = {"pods": [], "configmaps": [], "pvcs": []}
    
    # Should not raise, just log error
    await rc._cleanup_orphaned_configmaps("ns", cutoff, cleaned, dry_run=False)
    
    # ConfigMap should still be marked as cleaned
    assert "old-cm" in cleaned["configmaps"]


@pytest.mark.asyncio
async def test_get_resource_usage_with_failures(monkeypatch):
    """Test get_resource_usage handles partial failures gracefully."""
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", lambda: None)
    
    class PartiallyFailingV1:
        def list_namespaced_pod(self, namespace, label_selector=None):
            # Pods work fine
            return SimpleNamespace(items=[SimpleNamespace(metadata=SimpleNamespace(name="p1"))])
        
        def list_namespaced_config_map(self, namespace, label_selector=None):
            # ConfigMaps fail
            raise Exception("ConfigMaps API error")
    
    class FailingNet:
        def list_namespaced_network_policy(self, namespace, label_selector=None):
            # Network policies fail
            raise Exception("Network API error")
    
    monkeypatch.setattr(rcmod.k8s_client, "CoreV1Api", PartiallyFailingV1)
    monkeypatch.setattr(rcmod.k8s_client, "NetworkingV1Api", FailingNet)
    
    await rc.initialize()
    
    counts = await rc.get_resource_usage(namespace="ns")
    
    # Should return partial results
    assert counts["pods"] == 1
    assert counts["configmaps"] == 0  # Failed, defaulted to 0
    assert counts["network_policies"] == 0  # Failed, defaulted to 0


@pytest.mark.asyncio
async def test_get_resource_usage_not_initialized_v1(monkeypatch):
    """Test get_resource_usage when v1 client is not initialized."""
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", lambda: None)
    monkeypatch.setattr(rcmod.k8s_client, "NetworkingV1Api", lambda: FakeNet())
    
    # Don't set CoreV1Api, so v1 will be None
    rc._initialized = True
    rc.v1 = None
    rc.networking_v1 = FakeNet()
    
    counts = await rc.get_resource_usage(namespace="ns")
    
    # Should return defaults when clients are not available
    assert counts["pods"] == 0
    assert counts["configmaps"] == 0


@pytest.mark.asyncio
async def test_get_resource_usage_not_initialized_networking(monkeypatch):
    """Test get_resource_usage when networking client is not initialized."""
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", lambda: None)
    
    fake_v1 = FakeV1()
    fake_v1._pods = [SimpleNamespace(metadata=SimpleNamespace(name="p1"))]
    monkeypatch.setattr(rcmod.k8s_client, "CoreV1Api", lambda: fake_v1)
    
    # Don't set NetworkingV1Api, so networking_v1 will be None
    rc._initialized = True
    rc.v1 = fake_v1
    rc.networking_v1 = None
    
    counts = await rc.get_resource_usage(namespace="ns")
    
    # Should return partial results
    assert counts["pods"] == 1
    assert counts["network_policies"] == 0  # No networking client


@pytest.mark.asyncio
async def test_get_resource_usage_complete_failure(monkeypatch):
    """Test get_resource_usage returns defaults when everything fails."""
    rc = ResourceCleaner()
    import app.services.result_processor.resource_cleaner as rcmod
    monkeypatch.setattr(rcmod.k8s_config, "load_incluster_config", lambda: None)
    
    # Create a FakeV1 that raises exceptions for all list operations
    class FailingV1:
        def list_namespaced_pod(self, namespace, label_selector=None):
            raise Exception("Pod listing failed")
        
        def list_namespaced_config_map(self, namespace, label_selector=None):
            raise Exception("ConfigMap listing failed")
    
    # Create a FakeNet that raises exceptions
    class FailingNet:
        def list_namespaced_network_policy(self, namespace, label_selector=None):
            raise Exception("NetworkPolicy listing failed")
    
    monkeypatch.setattr(rcmod.k8s_client, "CoreV1Api", FailingV1)
    monkeypatch.setattr(rcmod.k8s_client, "NetworkingV1Api", FailingNet)
    
    await rc.initialize()
    
    counts = await rc.get_resource_usage(namespace="ns")
    
    # Should return default counts when all operations fail
    assert counts == {"pods": 0, "configmaps": 0, "network_policies": 0}

