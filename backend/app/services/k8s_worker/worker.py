import asyncio
import time
from pathlib import Path

import aiohttp
import structlog
from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client.rest import ApiException
from opentelemetry import trace

from app.domain.events import ExecutionRequestedEvent, PodCreatedEvent
from app.events import UnifiedProducer
from app.runtime_registry import RUNTIME_REGISTRY
from app.settings import Settings

from .pod_builder import PodBuilder


class KubernetesWorker:
    """Creates and deletes executor pods, and prepares the executor namespace at startup.

    The execution scheduler calls it once a queued execution gets a slot, and again to delete a cancelled one.
    """

    def __init__(
        self,
        api_client: k8s_client.ApiClient,
        producer: UnifiedProducer,
        settings: Settings,
        logger: structlog.stdlib.BoundLogger,
        tracer: trace.Tracer,
    ):
        self.logger = logger
        self._tracer = tracer
        self._settings = settings

        # Validate namespace
        if self._settings.K8S_NAMESPACE == "default":
            raise ValueError(
                "KubernetesWorker namespace 'default' is forbidden. Set K8S_NAMESPACE to a dedicated namespace."
            )

        # Kubernetes clients created from ApiClient
        self.v1 = k8s_client.CoreV1Api(api_client)
        self.apps_v1 = k8s_client.AppsV1Api(api_client)
        self.networking_v1 = k8s_client.NetworkingV1Api(api_client)

        # Components
        self.pod_builder = PodBuilder(settings=settings)
        self.producer = producer

        # State tracking
        self._active_creations: set[str] = set()

        self.logger.info("KubernetesWorker initialized", namespace=self._settings.K8S_NAMESPACE)

    async def delete_pod(self, execution_id: str) -> None:
        """Delete an execution's pod at once; K8s garbage-collects its ConfigMap through the ownerReference.

        A queued execution has no pod yet, so a 404 is expected.
        """
        pod_name = f"executor-{execution_id}"
        try:
            await self.v1.delete_namespaced_pod(
                name=pod_name,
                namespace=self._settings.K8S_NAMESPACE,
                grace_period_seconds=0,
            )
            self.logger.info("Deleted pod, K8s garbage-collects its ConfigMap", pod_name=pod_name)
        except ApiException as e:
            if e.status != 404:
                self.logger.warning("Failed to delete pod", execution_id=execution_id, status=e.status, reason=e.reason)

    async def create_pod(self, event: ExecutionRequestedEvent) -> None:
        """Create the ConfigMap and pod for an execution, then publish pod_created."""
        execution_id = event.execution_id
        self._active_creations.add(execution_id)

        with self._tracer.start_as_current_span("pod.create", attributes={"pod.language": event.language}) as span:
            start_time = time.time()
            try:
                entrypoint_content = await self._get_entrypoint_script()

                config_map = self.pod_builder.build_config_map(
                    event=event, script_content=event.script, entrypoint_content=entrypoint_content
                )
                await self._create_config_map(config_map)

                pod = self.pod_builder.build_pod_manifest(event=event)
                created_pod = await self._create_pod(pod)

                # Set ownerReference so K8s garbage-collects the ConfigMap when the pod is deleted
                if created_pod and created_pod.metadata and created_pod.metadata.uid:
                    await self._set_configmap_owner(config_map, created_pod)

                await self._publish_pod_created(event, pod)

                span.set_attribute("pod.creation_result", "success")
                self.logger.info(
                    "Created pod for execution",
                    pod_name=pod.metadata.name,
                    execution_id=execution_id,
                    duration_seconds=round(time.time() - start_time, 2),
                )
            except Exception:
                span.set_attribute("pod.creation_result", "failed")
                raise
            finally:
                self._active_creations.discard(execution_id)
                span.set_attribute("pod.active_creations", len(self._active_creations))

    async def _get_entrypoint_script(self) -> str:
        """Get entrypoint script content"""
        entrypoint_path = Path("app/scripts/entrypoint.sh")
        if entrypoint_path.exists():
            return await asyncio.to_thread(entrypoint_path.read_text)

        # Default entrypoint if file not found
        return """#!/bin/bash
set -e

# Set up output directory
OUTPUT_DIR="${OUTPUT_PATH:-/output}"
mkdir -p "$OUTPUT_DIR"

# Redirect output
exec > >(tee -a "$OUTPUT_DIR/stdout.log")
exec 2> >(tee -a "$OUTPUT_DIR/stderr.log" >&2)

# Execute the script
cd /script
exec "$@"
"""

    async def _create_config_map(self, config_map: k8s_client.V1ConfigMap) -> None:
        """Create ConfigMap in Kubernetes"""
        with self._tracer.start_as_current_span("pod.create_configmap") as span:
            try:
                await self.v1.create_namespaced_config_map(namespace=self._settings.K8S_NAMESPACE, body=config_map)
                span.set_attribute("pod.configmap_result", "success")
                self.logger.debug("Created ConfigMap", config_map=config_map.metadata.name)
            except ApiException as e:
                if e.status == 409:  # Already exists
                    self.logger.warning("ConfigMap already exists", config_map=config_map.metadata.name)
                    span.set_attribute("pod.configmap_result", "already_exists")
                else:
                    span.set_attribute("pod.configmap_result", "failed")
                    raise

    async def _create_pod(self, pod: k8s_client.V1Pod) -> k8s_client.V1Pod | None:
        """Create Pod in Kubernetes. Returns the created pod (with UID) or None if it already existed."""
        try:
            created: k8s_client.V1Pod = await self.v1.create_namespaced_pod(
                namespace=self._settings.K8S_NAMESPACE, body=pod
            )
            self.logger.debug("Created Pod", pod_name=pod.metadata.name)
            return created
        except ApiException as e:
            if e.status == 409:  # Already exists
                self.logger.warning("Pod already exists", pod_name=pod.metadata.name)
                return None
            else:
                raise

    async def _set_configmap_owner(self, config_map: k8s_client.V1ConfigMap, owner_pod: k8s_client.V1Pod) -> None:
        """Patch the ConfigMap with an ownerReference pointing to the pod.

        This makes K8s garbage-collect the ConfigMap automatically when the pod is deleted.
        """
        owner_ref = k8s_client.V1OwnerReference(
            api_version="v1",
            kind="Pod",
            name=owner_pod.metadata.name,
            uid=owner_pod.metadata.uid,
            block_owner_deletion=False,
        )
        patch_body = {"metadata": {"ownerReferences": [owner_ref]}}
        try:
            await self.v1.patch_namespaced_config_map(
                name=config_map.metadata.name,
                namespace=self._settings.K8S_NAMESPACE,
                body=patch_body,
            )
            self.logger.debug(
                "Set ownerReference on ConfigMap",
                config_map=config_map.metadata.name,
                pod_name=owner_pod.metadata.name,
            )
        except ApiException as e:
            self.logger.warning("Failed to set ownerReference on ConfigMap", reason=e.reason)

    async def _publish_pod_created(self, event: ExecutionRequestedEvent, pod: k8s_client.V1Pod) -> None:
        """Publish pod created event"""
        pod_created = PodCreatedEvent(
            execution_id=event.execution_id,
            aggregate_id=event.aggregate_id,
            pod_name=pod.metadata.name,
            namespace=pod.metadata.namespace,
            metadata=event.metadata,
        )
        await self.producer.produce(event_to_produce=pod_created, key=event.execution_id)

    async def ensure_namespace_security(self) -> None:
        """Create the executor namespace and apply its security controls at startup.

        Applies:
        - The namespace with Pod Security Admission labels (Restricted profile)
        - Default-deny NetworkPolicy for executor pods (blocks lateral movement and exfiltration)
        - ResourceQuota capping what all executor pods together may request
        """
        namespace = self._settings.K8S_NAMESPACE
        await self._apply_namespace(namespace)
        await self._ensure_executor_network_policy(namespace)
        await self._ensure_resource_quota(namespace)

    async def _ensure_executor_network_policy(self, namespace: str) -> None:
        """Create or update default-deny NetworkPolicy for executor pods."""
        policy_name = "executor-deny-all"

        policy = k8s_client.V1NetworkPolicy(
            api_version="networking.k8s.io/v1",
            kind="NetworkPolicy",
            metadata=k8s_client.V1ObjectMeta(
                name=policy_name,
                namespace=namespace,
                labels={"app": "integr8s", "component": "security"},
            ),
            spec=k8s_client.V1NetworkPolicySpec(
                pod_selector=k8s_client.V1LabelSelector(match_labels={"component": "executor"}),
                policy_types=["Ingress", "Egress"],
                ingress=[],
                egress=[],
            ),
        )

        await self.networking_v1.patch_namespaced_network_policy(  # type: ignore[call-arg]
            name=policy_name,
            namespace=namespace,
            body=policy,
            field_manager="integr8s",
            force=True,
            _content_type="application/apply-patch+yaml",
        )
        self.logger.info("NetworkPolicy applied", policy_name=policy_name, namespace=namespace)

    async def _apply_namespace(self, namespace: str) -> None:
        """Create or update the executor namespace with its Pod Security Admission labels."""
        psa_labels = {
            "pod-security.kubernetes.io/enforce": "restricted",
            "pod-security.kubernetes.io/enforce-version": "latest",
            "pod-security.kubernetes.io/warn": "restricted",
            "pod-security.kubernetes.io/audit": "restricted",
        }
        body = k8s_client.V1Namespace(
            api_version="v1",
            kind="Namespace",
            metadata=k8s_client.V1ObjectMeta(name=namespace, labels=psa_labels),
        )

        await self.v1.patch_namespace(  # type: ignore[call-arg]
            name=namespace,
            body=body,
            field_manager="integr8s",
            force=True,
            _content_type="application/apply-patch+yaml",
        )
        self.logger.info("Namespace applied with Pod Security Admission labels", namespace=namespace)

    async def _ensure_resource_quota(self, namespace: str) -> None:
        """Create or update the quota on what all pods in the executor namespace may request together."""
        quota_name = "executor-quota"
        quota = k8s_client.V1ResourceQuota(
            api_version="v1",
            kind="ResourceQuota",
            metadata=k8s_client.V1ObjectMeta(
                name=quota_name,
                namespace=namespace,
                labels={"app": "integr8s", "component": "security"},
            ),
            spec=k8s_client.V1ResourceQuotaSpec(
                hard={
                    "requests.cpu": self._settings.K8S_NAMESPACE_CPU_QUOTA,
                    "requests.memory": self._settings.K8S_NAMESPACE_MEMORY_QUOTA,
                }
            ),
        )

        await self.v1.patch_namespaced_resource_quota(  # type: ignore[call-arg]
            name=quota_name,
            namespace=namespace,
            body=quota,
            field_manager="integr8s",
            force=True,
            _content_type="application/apply-patch+yaml",
        )
        self.logger.info("ResourceQuota applied", quota_name=quota_name, namespace=namespace)

    async def ensure_image_pre_puller_daemonset(self) -> None:
        """Ensure the runtime image pre-puller DaemonSet exists."""
        daemonset_name = "runtime-image-pre-puller"
        namespace = self._settings.K8S_NAMESPACE

        try:
            init_containers: list[k8s_client.V1Container] = []
            all_images = {config.image for lang in RUNTIME_REGISTRY.values() for config in lang.values()}

            psa_security_context = k8s_client.V1SecurityContext(
                allow_privilege_escalation=False,
                capabilities=k8s_client.V1Capabilities(drop=["ALL"]),
                run_as_non_root=True,
                run_as_user=65534,
                seccomp_profile=k8s_client.V1SeccompProfile(type="RuntimeDefault"),
            )

            minimal_resources = k8s_client.V1ResourceRequirements(
                requests={"cpu": "10m", "memory": "8Mi"},
                limits={"cpu": "100m", "memory": "32Mi"},
            )

            for i, image_ref in enumerate(sorted(all_images)):
                sanitized_image_ref = image_ref.split("/")[-1].replace(":", "-").replace(".", "-").replace("_", "-")
                self.logger.info(
                    "Adding image to pre-puller DaemonSet", image=image_ref, sanitized_name=sanitized_image_ref
                )
                init_containers.append(
                    k8s_client.V1Container(
                        name=f"pull-{i}-{sanitized_image_ref}",
                        image=image_ref,
                        command=["/bin/sh", "-c", f'echo "Image {image_ref} pulled."'],
                        image_pull_policy="Always",
                        security_context=psa_security_context,
                        resources=minimal_resources,
                    )
                )

            daemonset = k8s_client.V1DaemonSet(
                api_version="apps/v1",
                kind="DaemonSet",
                metadata=k8s_client.V1ObjectMeta(name=daemonset_name, namespace=namespace),
                spec=k8s_client.V1DaemonSetSpec(
                    selector=k8s_client.V1LabelSelector(match_labels={"name": daemonset_name}),
                    template=k8s_client.V1PodTemplateSpec(
                        metadata=k8s_client.V1ObjectMeta(labels={"name": daemonset_name}),
                        spec=k8s_client.V1PodSpec(
                            init_containers=init_containers,
                            containers=[
                                k8s_client.V1Container(
                                    name="pause",
                                    image="registry.k8s.io/pause:3.9",
                                    security_context=psa_security_context,
                                    resources=minimal_resources,
                                )
                            ],
                            tolerations=[k8s_client.V1Toleration(operator="Exists")],
                            security_context=k8s_client.V1PodSecurityContext(
                                run_as_non_root=True,
                                run_as_user=65534,
                                seccomp_profile=k8s_client.V1SeccompProfile(type="RuntimeDefault"),
                            ),
                        ),
                    ),
                    update_strategy=k8s_client.V1DaemonSetUpdateStrategy(type="RollingUpdate"),
                ),
            )

            await self.apps_v1.patch_namespaced_daemon_set(  # type: ignore[call-arg]
                name=daemonset_name,
                namespace=namespace,
                body=daemonset,
                field_manager="integr8s",
                force=True,
                _content_type="application/apply-patch+yaml",
            )
            self.logger.info("DaemonSet applied", daemonset=daemonset_name)

        except ApiException as e:
            self.logger.error(
                "K8s API error applying DaemonSet", daemonset=daemonset_name, reason=e.reason, exc_info=True
            )
        except aiohttp.ClientError, TimeoutError:
            self.logger.error("Could not reach K8s API applying DaemonSet", daemonset=daemonset_name, exc_info=True)
