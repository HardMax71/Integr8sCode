from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from kubernetes_asyncio import client as k8s_client
from opentelemetry import trace

from app.events.core import UnifiedProducer
from app.services.k8s_worker import KubernetesWorker
from app.settings import Settings

pytestmark = pytest.mark.unit

SERVER_SIDE_APPLY = {"field_manager": "integr8s", "force": True, "_content_type": "application/apply-patch+yaml"}


async def test_namespace_security_applies_namespace_policy_and_quota(
    test_settings: Settings, tracer: trace.Tracer
) -> None:
    settings = test_settings.model_copy(update={"K8S_NAMESPACE_CPU_QUOTA": "8", "K8S_NAMESPACE_MEMORY_QUOTA": "2Gi"})
    worker = KubernetesWorker(
        api_client=MagicMock(spec=k8s_client.ApiClient),
        producer=AsyncMock(spec=UnifiedProducer),
        settings=settings,
        logger=MagicMock(spec=structlog.stdlib.BoundLogger),
        tracer=tracer,
    )
    core = MagicMock(patch_namespace=AsyncMock(), patch_namespaced_resource_quota=AsyncMock())
    networking = MagicMock(patch_namespaced_network_policy=AsyncMock())
    worker.v1 = core
    worker.networking_v1 = networking

    await worker.ensure_namespace_security()

    namespace_call = core.patch_namespace.await_args
    assert namespace_call is not None
    assert namespace_call.kwargs["name"] == settings.K8S_NAMESPACE
    assert namespace_call.kwargs["body"].metadata.labels["pod-security.kubernetes.io/enforce"] == "restricted"
    assert {k: namespace_call.kwargs[k] for k in SERVER_SIDE_APPLY} == SERVER_SIDE_APPLY

    policy_call = networking.patch_namespaced_network_policy.await_args
    assert policy_call is not None
    assert policy_call.kwargs["body"].spec.policy_types == ["Ingress", "Egress"]

    quota_call = core.patch_namespaced_resource_quota.await_args
    assert quota_call is not None
    assert quota_call.kwargs["namespace"] == settings.K8S_NAMESPACE
    assert quota_call.kwargs["body"].spec.hard == {"requests.cpu": "8", "requests.memory": "2Gi"}
    assert {k: quota_call.kwargs[k] for k in SERVER_SIDE_APPLY} == SERVER_SIDE_APPLY
