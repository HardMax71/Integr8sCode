# mypy: disable-error-code="slop-any-check"
# Rationale: kubernetes client 31.0.0 has no type annotations (all Any)
import logging
from dataclasses import dataclass

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes import watch as k8s_watch


@dataclass(frozen=True)
class K8sClients:
    """Kubernetes API clients bundle for dependency injection."""

    api_client: k8s_client.ApiClient
    v1: k8s_client.CoreV1Api
    apps_v1: k8s_client.AppsV1Api
    networking_v1: k8s_client.NetworkingV1Api
    watch: k8s_watch.Watch


def create_k8s_clients(
    logger: logging.Logger, kubeconfig_path: str | None = None, in_cluster: bool | None = None
) -> K8sClients:
    if in_cluster:
        k8s_config.load_incluster_config()
    elif kubeconfig_path:
        k8s_config.load_kube_config(config_file=kubeconfig_path)
    else:
        k8s_config.load_kube_config()

    configuration = k8s_client.Configuration.get_default_copy()
    logger.info(f"Kubernetes API host: {configuration.host}")
    logger.info(f"SSL CA configured: {configuration.ssl_ca_cert is not None}")

    api_client = k8s_client.ApiClient(configuration)
    return K8sClients(
        api_client=api_client,
        v1=k8s_client.CoreV1Api(api_client),
        apps_v1=k8s_client.AppsV1Api(api_client),
        networking_v1=k8s_client.NetworkingV1Api(api_client),
        watch=k8s_watch.Watch(),
    )


def close_k8s_clients(clients: K8sClients) -> None:
    close = getattr(clients.api_client, "close", None)
    if callable(close):
        close()
