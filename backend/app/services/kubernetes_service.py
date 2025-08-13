import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import Depends, Request
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes import watch
from kubernetes.client.rest import ApiException

from app.config import get_settings
from app.core.logging import logger
from app.core.metrics import NETWORK_POLICY_VIOLATIONS, POD_EVENT_PUBLISHED, SECURITY_EVENTS
from app.events.kafka.cb import CircuitBreaker, CircuitBreakerType
from app.runtime_registry import RUNTIME_REGISTRY
from app.schemas_avro.event_schemas import EventType
from app.services.kafka_event_service import KafkaEventService
from app.services.network_policy import NetworkPolicyBuilder
from app.services.pod_manifest_builder import PodManifestBuilder


class KubernetesServiceError(Exception):
    pass


class KubernetesPodError(KubernetesServiceError):
    pass


class KubernetesConfigError(KubernetesServiceError):
    pass


_K8S_CLIENT_NOT_INITIALIZED_MSG: str = "Kubernetes client not initialized."


class KubernetesServiceManager:
    def __init__(self) -> None:
        self.services: Set["KubernetesService"] = set()

    def register(self, service: "KubernetesService") -> None:
        self.services.add(service)

    def unregister(self, service: "KubernetesService") -> None:
        self.services.discard(service)

    async def shutdown_all(self) -> None:
        for service in self.services:
            try:
                await service.graceful_shutdown()
            except Exception as e:
                logger.error(f"Error shutting down K8s service: {str(e)}")
            self.services.discard(service)


class KubernetesService:
    NAMESPACE = "integr8scode"
    POD_RETRY_ATTEMPTS = 15
    POD_RETRY_INTERVAL = 1
    POD_SUCCESS_STATES = {"Succeeded", "Failed"}
    SHUTDOWN_TIMEOUT = 30
    HEALTH_CHECK_INTERVAL = 60
    CONTAINER_KUBECONFIG_PATH = "/app/kubeconfig.yaml"

    v1: Optional[k8s_client.CoreV1Api]
    apps_v1: Optional[k8s_client.AppsV1Api]
    networking_v1: Optional[k8s_client.NetworkingV1Api]
    version_api: Optional[k8s_client.VersionApi]

    def __init__(self, manager: KubernetesServiceManager):
        self.settings = get_settings()
        self.manager = manager
        self.event_service: Optional[KafkaEventService] = None
        self.v1 = None
        self.apps_v1 = None
        self.networking_v1 = None
        self.version_api = None
        self._initialize_kubernetes_client()

        self.circuit_breaker = CircuitBreaker(service_name="kubernetes", breaker_type=CircuitBreakerType.GENERAL)
        self._active_pods: Dict[str, datetime] = {}
        self._is_healthy = True
        self._last_health_check = datetime.now(timezone.utc)
        self._pending_pod_events: List[Dict[str, Any]] = []

        self.manager.register(self)

    def set_event_service(self, event_service: KafkaEventService) -> None:
        """Set the event service for publishing pod events"""
        self.event_service = event_service
        logger.info("Event service configured for KubernetesService")

    def __del__(self) -> None:
        self.manager.unregister(self)

    async def check_health(self) -> bool:
        if not self.version_api:
            logger.warning("Kubernetes client not available for health check.")
            self._is_healthy = False
            return False
        try:
            if (datetime.now(timezone.utc) - self._last_health_check).seconds < self.HEALTH_CHECK_INTERVAL:
                return self._is_healthy
            await asyncio.to_thread(self.version_api.get_code)
            self._is_healthy = True
            await self.circuit_breaker.record_success()
            self._last_health_check = datetime.now(timezone.utc)
            return True
        except Exception as e:
            logger.error(f"Kubernetes health check failed: {str(e)}")
            self._is_healthy = False
            await self.circuit_breaker.record_failure()
            self._last_health_check = datetime.now(timezone.utc)
            return False

    async def graceful_shutdown(self) -> None:
        shutdown_deadline = datetime.now(timezone.utc) + timedelta(seconds=self.SHUTDOWN_TIMEOUT)
        for pod_name in list(self._active_pods.keys()):
            if datetime.now(timezone.utc) > shutdown_deadline:
                logger.warning("Shutdown timeout reached, forcing pod termination")
                break
            try:
                if not pod_name.startswith("execution-"):
                    return
                execution_id = pod_name[len("execution-"):]
                config_map_name = f"script-{execution_id}"
                await self._cleanup_resources(pod_name, config_map_name, execution_id)
            except Exception as e:
                logger.error(f"Error during pod cleanup on shutdown: {str(e)}")

    def _initialize_kubernetes_client(self) -> None:
        try:
            self._setup_kubernetes_config()
            self.v1 = k8s_client.CoreV1Api()
            self.apps_v1 = k8s_client.AppsV1Api()
            self.networking_v1 = k8s_client.NetworkingV1Api()
            self.version_api = k8s_client.VersionApi()
            self._test_api_connection()
            logger.info("Kubernetes client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {str(e)}")
            self.v1 = None
            self.apps_v1 = None
            self.networking_v1 = None
            self.version_api = None
            raise KubernetesConfigError(f"Failed to initialize Kubernetes client: {str(e)}") from e

    def _setup_kubernetes_config(self) -> None:
        if os.path.exists(self.CONTAINER_KUBECONFIG_PATH):
            logger.info(f"Using kubeconfig from {self.CONTAINER_KUBECONFIG_PATH}")
            k8s_config.load_kube_config(config_file=self.CONTAINER_KUBECONFIG_PATH)
        elif os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount"):
            logger.info("Using in-cluster Kubernetes configuration")
            k8s_config.load_incluster_config()
        else:
            default_kube_path = os.path.expanduser(self.settings.KUBERNETES_CONFIG_PATH)
            if not os.path.exists(default_kube_path):
                raise KubernetesConfigError("Could not find valid Kubernetes configuration.")

            logger.info(f"Using default kubeconfig from {default_kube_path}")
            k8s_config.load_kube_config(config_file=default_kube_path)

        default_config = k8s_client.Configuration.get_default_copy()
        logger.info(f"Kubernetes client configured for host: {default_config.host}")

    def _test_api_connection(self) -> None:
        if not self.version_api:
            raise KubernetesConfigError("VersionAPI client not initialized.")
        try:
            version = self.version_api.get_code()
            logger.info(f"Successfully connected to Kubernetes API. Server version: {version.git_version}")
        except Exception as e:
            logger.error(f"Unexpected error during K8s API connection test: {str(e)}")
            raise KubernetesConfigError(f"Unexpected error connecting to Kubernetes API: {str(e)}") from e

    async def create_execution_pod(
            self,
            execution_id: str,
            image: str,
            command: List[str],
            config_map_data: Dict[str, str]
    ) -> None:
        if self.circuit_breaker.is_open:
            raise KubernetesServiceError("Service circuit breaker is open")
        if not await self.check_health():
            raise KubernetesServiceError("Kubernetes service is unhealthy")

        config_map_name = f"script-{execution_id}"
        pod_name = f"execution-{execution_id}"

        try:
            entrypoint_script_path = Path("app/scripts/entrypoint.sh")
            entrypoint_code = await asyncio.to_thread(entrypoint_script_path.read_text)

            config_map_data["entrypoint.sh"] = entrypoint_code

            config_map_body = k8s_client.V1ConfigMap(
                metadata=k8s_client.V1ObjectMeta(name=config_map_name),
                data=config_map_data
            )
            await self._create_config_map(config_map_body)

            final_pod_command = ["/bin/sh", "/entry/entrypoint.sh", *command]

            builder = PodManifestBuilder(
                execution_id=execution_id,
                config_map_name=config_map_name,
                image=image,
                command=final_pod_command,
                pod_cpu_limit=self.settings.K8S_POD_CPU_LIMIT,
                pod_cpu_request=self.settings.K8S_POD_CPU_REQUEST,
                pod_memory_limit=self.settings.K8S_POD_MEMORY_LIMIT,
                pod_memory_request=self.settings.K8S_POD_MEMORY_REQUEST,
                pod_execution_timeout=self.settings.K8S_POD_EXECUTION_TIMEOUT,
                priority_class_name=self.settings.K8S_POD_PRIORITY_CLASS_NAME,
            )
            pod_manifest = builder.build()
            await self._create_namespaced_pod(pod_manifest)

            policy_builder = NetworkPolicyBuilder(execution_id, self.NAMESPACE)
            policy_manifest = policy_builder.build()
            await self._create_network_policy(policy_manifest)

            self._active_pods[execution_id] = datetime.now(timezone.utc)
            logger.info(f"Successfully created pod '{pod_name}' with image '{image}'")

            # Track security event - pod creation with restricted security context
            SECURITY_EVENTS.labels(event_type="SecurePodCreated").inc()

            # Publish pod created event
            if self.event_service:
                await self.event_service.publish_pod_event(
                    event_type=EventType.POD_CREATED.value,
                    pod_name=pod_name,
                    execution_id=execution_id,
                    namespace=self.NAMESPACE,
                    metadata={
                        "image": image,
                        "config_map_name": config_map_name
                    }
                )

            await self.circuit_breaker.record_success()

        except Exception as e:
            logger.error(f"Failed to create execution pod '{execution_id}': {str(e)}", exc_info=True)
            await self.circuit_breaker.record_failure()
            await self._cleanup_resources(pod_name, config_map_name, execution_id)
            raise KubernetesPodError(f"Failed to create execution pod: {str(e)}") from e

    async def get_pod_logs(self, execution_id: str) -> tuple[dict, str]:
        pod_name = f"execution-{execution_id}"
        config_map_name = f"script-{execution_id}"
        try:
            pod = await self._wait_for_pod_completion(pod_name)
            pod_phase = pod.status.phase if pod and pod.status else "Unknown"

            # Publish pod completed event
            if self.event_service:
                await self.event_service.publish_pod_event(
                    event_type="pod.completed",
                    pod_name=pod_name,
                    execution_id=execution_id,
                    namespace=self.NAMESPACE,
                    status=pod_phase
                )

            full_logs = await self._get_container_logs(pod_name, "executor")
            logger.info(f"Raw logs from pod {pod_name}:\n---\n{full_logs}\n---")

            try:
                # Parse the JSON output from the entrypoint script
                metrics = json.loads(full_logs.strip())
                return metrics, pod_phase
            except json.JSONDecodeError as e:
                logger.error(f"FAILED TO PARSE LOGS FROM POD {pod_name} as JSON: {e}"
                             f"Internal execution error: Pod logs were not valid JSON. "
                             f"Pod phase: {pod_phase}.\nRaw Logs:\n{full_logs}")
                error_payload = {
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": "Container execution failed - invalid output format",
                    "resource_usage": None,
                }
                return error_payload, pod_phase
        finally:
            logger.info(f"Initiating cleanup for execution '{execution_id}'...")
            await self._cleanup_resources(pod_name, config_map_name, execution_id)
            self._active_pods.pop(execution_id, None)

    async def _wait_for_pod_completion(self, pod_name: str) -> k8s_client.V1Pod:
        if not self.v1:
            raise KubernetesServiceError(_K8S_CLIENT_NOT_INITIALIZED_MSG)

        w = watch.Watch()

        # Clear any pending events
        self._pending_pod_events = []

        # Run the watch in a thread
        pod = await asyncio.to_thread(self._watch_pod, w, pod_name)

        # Publish all pending pod events
        if self._pending_pod_events and self.event_service:
            for event in self._pending_pod_events:
                await self._publish_pod_event(**event)
            self._pending_pod_events = []

        return pod

    def _watch_pod(self, w: watch.Watch, pod_name: str) -> k8s_client.V1Pod:
        execution_id = pod_name[len("execution-"):] if pod_name.startswith("execution-") else None

        # Initialize list to store all pod events
        if not hasattr(self, '_pending_pod_events'):
            self._pending_pod_events = []

        if not self.v1:
            logger.error("Kubernetes client not initialized")
            return
        
        for event in w.stream(
                self.v1.list_namespaced_pod,
                namespace=self.NAMESPACE,
                field_selector=f"metadata.name={pod_name}",
                timeout_seconds=300
        ):
            pod = event['object']
            event_type = event['type']

            # Store all pod events to be published later (since we're in a sync context)
            if self.event_service and execution_id:
                self._pending_pod_events.append({
                    "event_type": event_type,
                    "pod": pod,
                    "pod_name": pod_name,
                    "execution_id": execution_id
                })

            if event_type == 'DELETED':
                raise KubernetesPodError(f"Pod '{pod_name}' was deleted")

            if pod.status and pod.status.phase in self.POD_SUCCESS_STATES:
                logger.info(f"Pod '{pod_name}' completed: {pod.status.phase}")
                return pod

        raise KubernetesPodError(f"Pod '{pod_name}' watch timeout")

    async def _publish_pod_event(
            self,
            event_type: str,
            pod: k8s_client.V1Pod,
            pod_name: str,
            execution_id: str
    ) -> None:
        """Publish pod events to event service"""
        try:
            # Map Kubernetes event types to our event types
            event_type_map = {
                "ADDED": EventType.POD_CREATED.value,
                "MODIFIED": "pod.updated",
                "DELETED": EventType.POD_DELETED.value
            }

            our_event_type = event_type_map.get(event_type, f"pod.{event_type.lower()}")

            # Extract pod status information
            pod_status: dict[str, Any] = {
                "phase": pod.status.phase if pod.status else None,
                "reason": pod.status.reason if pod.status else None,
                "message": pod.status.message if pod.status else None,
                "conditions": [],
                "container_statuses": []
            }

            if pod.status and pod.status.conditions:
                pod_status["conditions"] = [
                    {
                        "type": condition.type,
                        "status": condition.status,
                        "reason": condition.reason,
                        "message": condition.message
                    }
                    for condition in pod.status.conditions
                ]

            if pod.status and pod.status.container_statuses:
                pod_status["container_statuses"] = [
                    {
                        "name": cs.name,
                        "ready": cs.ready,
                        "restart_count": cs.restart_count,
                        "state": {
                            "running": cs.state.running is not None if cs.state else False,
                            "terminated": cs.state.terminated is not None if cs.state else False,
                            "waiting": cs.state.waiting is not None if cs.state else False
                        }
                    }
                    for cs in pod.status.container_statuses
                ]

            creation_timestamp = pod.metadata.creation_timestamp.isoformat() \
                if pod.metadata and pod.metadata.creation_timestamp else None
            if self.event_service:
                await self.event_service.publish_pod_event(
                    event_type=our_event_type,
                    pod_name=pod_name,
                    execution_id=execution_id,
                    namespace=self.NAMESPACE,
                    status=pod.status.phase if pod.status else None,
                    metadata={
                        "phase": pod.status.phase if pod.status else None,
                        "pod_status": pod_status,
                        "labels": pod.metadata.labels if pod.metadata else {},
                        "creation_timestamp": creation_timestamp
                    }
                )

            # Track pod event metrics
            POD_EVENT_PUBLISHED.labels(
                event_type=our_event_type,
                phase=pod.status.phase if pod.status else "unknown"
            ).inc()

        except Exception as e:
            logger.error(f"Failed to publish pod event: {e}", exc_info=True)

    async def _get_container_logs(self, pod_name: str, container_name: str) -> str:
        if not self.v1:
            return f"Error: {_K8S_CLIENT_NOT_INITIALIZED_MSG}"
        try:
            return await asyncio.to_thread(
                self.v1.read_namespaced_pod_log,
                name=pod_name,
                namespace=self.NAMESPACE,
                container=container_name,
            )
        except ApiException as e:
            logger.error(f"Could not retrieve logs for {container_name} in {pod_name}: {e.reason}")
            return f"Error retrieving logs: {e.reason}"

    async def _create_config_map(self, config_map: k8s_client.V1ConfigMap) -> None:
        if not self.v1:
            raise KubernetesServiceError(_K8S_CLIENT_NOT_INITIALIZED_MSG)
        try:
            await asyncio.to_thread(self.v1.create_namespaced_config_map, namespace=self.NAMESPACE, body=config_map)
            logger.info(f"ConfigMap '{config_map.metadata.name}' created successfully.")
        except ApiException as e:
            logger.error(f"Failed to create ConfigMap '{config_map.metadata.name}': {e.status} {e.reason}")
            raise KubernetesServiceError(f"Failed to create ConfigMap: {str(e)}") from e

    async def _create_namespaced_pod(self, pod_manifest: Dict[str, Any]) -> None:
        if not self.v1:
            raise KubernetesPodError(_K8S_CLIENT_NOT_INITIALIZED_MSG)
        pod_name = pod_manifest.get("metadata", {}).get("name", "unknown-pod")
        try:
            await asyncio.to_thread(self.v1.create_namespaced_pod, body=pod_manifest, namespace=self.NAMESPACE)
            logger.info(f"Pod '{pod_name}' created successfully.")
        except ApiException as e:
            logger.error(f"Failed to create pod '{pod_name}': {e.status} {e.reason}")
            raise KubernetesPodError(f"Failed to create pod: {str(e)}") from e

    async def _cleanup_resources(self, pod_name: str, config_map_name: str, execution_id: Optional[str] = None) -> None:
        if not self.v1:
            return
        try:
            await asyncio.to_thread(self.v1.delete_namespaced_pod, name=pod_name, namespace=self.NAMESPACE)
            logger.info(f"Deletion request sent for pod '{pod_name}'")

            # Publish pod cleanup event
            if self.event_service and execution_id:
                await self.event_service.publish_pod_event(
                    event_type="pod.cleanup",
                    pod_name=pod_name,
                    execution_id=execution_id,
                    namespace=self.NAMESPACE,
                    metadata={"action": "delete_requested"}
                )
        except ApiException as e:
            logger.error(f"Failed to send deletion request for pod '{pod_name}': {e.reason}")

        try:
            await asyncio.to_thread(self.v1.delete_namespaced_config_map, name=config_map_name,
                                    namespace=self.NAMESPACE)
            logger.info(f"Deletion request sent for config map '{config_map_name}'")
        except ApiException as e:
            logger.error(f"Failed to delete config map '{config_map_name}': {e.reason}")

        if execution_id:
            policy_name = f"deny-external-{execution_id}"
            await self._delete_network_policy(policy_name)

    async def _create_network_policy(self, policy_manifest: Dict[str, Any]) -> None:
        if not self.networking_v1:
            raise KubernetesServiceError("NetworkingV1Api client not initialized.")
        policy_name = policy_manifest.get("metadata", {}).get("name", "unknown-policy")
        try:
            await asyncio.to_thread(
                self.networking_v1.create_namespaced_network_policy,
                body=policy_manifest,
                namespace=self.NAMESPACE
            )
            logger.info(f"NetworkPolicy '{policy_name}' created successfully.")

            # Track security event - network policy creation
            SECURITY_EVENTS.labels(event_type="NetworkPolicyCreated").inc()
        except ApiException as e:
            logger.error(f"Failed to create NetworkPolicy '{policy_name}': {e.status} {e.reason}")

            # Track network policy creation failure
            NETWORK_POLICY_VIOLATIONS.labels(policy_name=policy_name).inc()

            raise KubernetesServiceError(f"Failed to create NetworkPolicy: {str(e)}") from e

    async def _delete_network_policy(self, policy_name: str) -> None:
        if not self.networking_v1:
            return
        try:
            await asyncio.to_thread(
                self.networking_v1.delete_namespaced_network_policy,
                name=policy_name,
                namespace=self.NAMESPACE
            )
            logger.info(f"Deletion request sent for NetworkPolicy '{policy_name}'")
        except ApiException as e:
            logger.error(f"Failed to delete NetworkPolicy '{policy_name}': {e.reason}")

    # DaemonSet: https://kubernetes.io/docs/concepts/workloads/controllers/daemonset/
    async def ensure_image_pre_puller_daemonset(self) -> None:
        if not self.apps_v1:
            logger.warning("Kubernetes AppsV1Api client not initialized. Skipping DaemonSet creation.")
            return

        daemonset_name = "runtime-image-pre-puller"
        namespace = self.NAMESPACE
        await asyncio.sleep(5)

        try:
            init_containers = []
            all_images = {
                config.image
                for lang in RUNTIME_REGISTRY.values()
                for config in lang.values()
            }

            for i, image_ref in enumerate(sorted(list(all_images))):
                sanitized_image_ref = image_ref.split('/')[-1].replace(':', '-').replace('.', '-').replace('_', '-')
                logger.info(f"DAEMONSET: before: {image_ref} -> {sanitized_image_ref}")
                container_name = f"pull-{i}-{sanitized_image_ref}"
                init_containers.append({
                    "name": container_name,
                    "image": image_ref,
                    "command": ["/bin/sh", "-c", f'echo "Image {image_ref} pulled."'],
                    "imagePullPolicy": "Always",
                })

            manifest: Dict[str, Any] = {
                "apiVersion": "apps/v1",
                "kind": "DaemonSet",
                "metadata": {"name": daemonset_name, "namespace": namespace},
                "spec": {
                    "selector": {"matchLabels": {"name": daemonset_name}},
                    "template": {
                        "metadata": {"labels": {"name": daemonset_name}},
                        "spec": {
                            "initContainers": init_containers,
                            "containers": [{
                                "name": "pause",
                                "image": "registry.k8s.io/pause:3.9"
                            }],
                            "tolerations": [{"operator": "Exists"}]
                        }
                    },
                    "updateStrategy": {"type": "RollingUpdate"}
                }
            }

            try:
                await asyncio.to_thread(self.apps_v1.read_namespaced_daemon_set, name=daemonset_name,
                                        namespace=namespace)
                logger.info(f"DaemonSet '{daemonset_name}' exists. Replacing to ensure it is up-to-date.")
                await asyncio.to_thread(
                    self.apps_v1.replace_namespaced_daemon_set,
                    name=daemonset_name, namespace=namespace, body=manifest
                )
                logger.info(f"DaemonSet '{daemonset_name}' replaced successfully.")
            except ApiException as e:
                if e.status == 404:
                    logger.info(f"DaemonSet '{daemonset_name}' not found. Creating...")
                    await asyncio.to_thread(
                        self.apps_v1.create_namespaced_daemon_set, namespace=namespace, body=manifest
                    )
                    logger.info(f"DaemonSet '{daemonset_name}' created successfully.")
                else:
                    raise

        except ApiException as e:
            logger.error(f"K8s API error applying DaemonSet '{daemonset_name}': {e.reason}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error applying image-puller DaemonSet: {e}", exc_info=True)


def get_k8s_manager(request: Request) -> KubernetesServiceManager:
    if not hasattr(request.app.state, "k8s_manager"):
        request.app.state.k8s_manager = KubernetesServiceManager()
    return request.app.state.k8s_manager  # type: ignore


def get_kubernetes_service(
        request: Request,
        manager: KubernetesServiceManager = Depends(get_k8s_manager)
) -> KubernetesService:
    if not hasattr(request.app.state, "k8s_service"):
        logger.info("Creating new KubernetesService singleton instance.")
        request.app.state.k8s_service = KubernetesService(manager)
    return request.app.state.k8s_service  # type: ignore
