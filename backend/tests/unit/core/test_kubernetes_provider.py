from pathlib import Path
from unittest.mock import MagicMock

import pytest
import structlog
from dishka import Provider, Scope, make_async_container
from kubernetes_asyncio import client as k8s_client

from app.core.providers import KubernetesProvider
from app.settings import Settings

pytestmark = pytest.mark.unit

K3S_KUBECONFIG = """\
apiVersion: v1
kind: Config
clusters:
- name: default
  cluster:
    server: https://127.0.0.1:6443
    insecure-skip-tls-verify: true
users:
- name: default
  user:
    token: k3s-token
contexts:
- name: default
  context:
    cluster: default
    user: default
current-context: default
"""


async def test_api_client_reaches_k3s_through_the_configured_server(test_settings: Settings, tmp_path: Path) -> None:
    kubeconfig = tmp_path / "k3s.yaml"
    kubeconfig.write_text(K3S_KUBECONFIG)
    settings = test_settings.model_copy(
        update={"KUBERNETES_CONFIG_PATH": str(kubeconfig), "KUBERNETES_API_SERVER": "https://k3s.example:6443"}
    )
    context = Provider(scope=Scope.APP)
    context.from_context(provides=Settings, scope=Scope.APP)
    context.from_context(provides=structlog.stdlib.BoundLogger, scope=Scope.APP)
    container = make_async_container(
        KubernetesProvider(),
        context,
        context={Settings: settings, structlog.stdlib.BoundLogger: MagicMock(spec=structlog.stdlib.BoundLogger)},
    )

    api_client = await container.get(k8s_client.ApiClient)

    assert api_client.configuration.host == "https://k3s.example:6443"
    assert api_client.configuration.api_key == {"BearerToken": "Bearer k3s-token"}
    await container.close()
