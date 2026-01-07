import logging
from dataclasses import dataclass

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio import config as k8s_config


@dataclass(frozen=True)
class K8sClients:
    """Container for Kubernetes API clients (kubernetes_asyncio)."""

    api_client: k8s_client.ApiClient
    v1: k8s_client.CoreV1Api
    apps_v1: k8s_client.AppsV1Api
    networking_v1: k8s_client.NetworkingV1Api


async def create_k8s_clients(
    logger: logging.Logger, kubeconfig_path: str | None = None, in_cluster: bool | None = None
) -> K8sClients:
    """Create Kubernetes API clients (async for kubernetes_asyncio)."""
    if in_cluster:
        k8s_config.load_incluster_config()
    else:
        await k8s_config.load_kube_config(config_file=kubeconfig_path)  # None → default ~/.kube/config

    # Create API client for kubernetes_asyncio
    api_client = k8s_client.ApiClient()
    configuration = api_client.configuration

    logger.info(f"Kubernetes API host: {configuration.host}")
    logger.info(f"SSL CA configured: {configuration.ssl_ca_cert is not None}")

    return K8sClients(
        api_client=api_client,
        v1=k8s_client.CoreV1Api(api_client),
        apps_v1=k8s_client.AppsV1Api(api_client),
        networking_v1=k8s_client.NetworkingV1Api(api_client),
    )


async def close_k8s_clients(clients: K8sClients) -> None:
    """Close Kubernetes API client (async for kubernetes_asyncio)."""
    if clients.api_client:
        await clients.api_client.close()
