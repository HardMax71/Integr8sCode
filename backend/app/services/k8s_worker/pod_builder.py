from kubernetes_asyncio import client as k8s_client

from app.infrastructure.kafka.events.saga import CreatePodCommandEvent
from app.services.k8s_worker.config import K8sWorkerConfig


class PodBuilder:
    def __init__(self, namespace: str = "integr8scode", config: K8sWorkerConfig | None = None):
        self.namespace = namespace
        self.config = config or K8sWorkerConfig()

    def build_pod_manifest(self, command: CreatePodCommandEvent) -> k8s_client.V1Pod:
        execution_id = command.execution_id
        pod_name = f"executor-{execution_id}"

        container = self._build_container(command)
        pod_spec = self._build_pod_spec(container, command)

        metadata = self._build_pod_metadata(
            name=pod_name,
            execution_id=execution_id,
            user_id=command.metadata.user_id,
            language=command.language,
            correlation_id=command.metadata.correlation_id,
            saga_id=command.saga_id,
        )

        return k8s_client.V1Pod(api_version="v1", kind="Pod", metadata=metadata, spec=pod_spec)

    def build_config_map(
        self, command: CreatePodCommandEvent, script_content: str, entrypoint_content: str
    ) -> k8s_client.V1ConfigMap:
        """Build ConfigMap for script and entrypoint"""
        execution_id = command.execution_id

        return k8s_client.V1ConfigMap(
            api_version="v1",
            kind="ConfigMap",
            metadata=k8s_client.V1ObjectMeta(
                name=f"script-{execution_id}",
                namespace=self.namespace,
                labels={
                    "app": "integr8s",
                    "component": "execution-script",
                    "execution-id": execution_id,
                    "saga-id": command.saga_id,
                },
            ),
            data={command.runtime_filename: script_content, "entrypoint.sh": entrypoint_content},
        )

    def _build_container(self, command: CreatePodCommandEvent) -> k8s_client.V1Container:
        execution_id = command.execution_id

        # Timeout is enforced by activeDeadlineSeconds on the pod spec
        container_command = ["/bin/sh", "/entry/entrypoint.sh"] + command.runtime_command

        # Get resources - prefer command values, fallback to config
        cpu_request = command.cpu_request or self.config.default_cpu_request
        memory_request = command.memory_request or self.config.default_memory_request
        cpu_limit = command.cpu_limit or self.config.default_cpu_limit
        memory_limit = command.memory_limit or self.config.default_memory_limit

        container = k8s_client.V1Container(
            name="executor",
            image=command.runtime_image,
            command=container_command,
            volume_mounts=[
                k8s_client.V1VolumeMount(name="script-volume", mount_path="/scripts", read_only=True),
                k8s_client.V1VolumeMount(name="entrypoint-volume", mount_path="/entry", read_only=True),
                k8s_client.V1VolumeMount(name="output-volume", mount_path="/output"),
                k8s_client.V1VolumeMount(name="tmp-volume", mount_path="/tmp"),  # nosec B108: K8s EmptyDir mounted inside container; not host /tmp
            ],
            resources=k8s_client.V1ResourceRequirements(
                requests={"cpu": cpu_request, "memory": memory_request},
                limits={"cpu": cpu_limit, "memory": memory_limit},
            ),
            env=[
                k8s_client.V1EnvVar(name="EXECUTION_ID", value=execution_id),
                k8s_client.V1EnvVar(name="OUTPUT_PATH", value="/output"),
            ],
        )

        # SECURITY: Always enforce strict security context
        container.security_context = k8s_client.V1SecurityContext(
            run_as_non_root=True,  # Always run as non-root
            run_as_user=1000,
            run_as_group=1000,
            read_only_root_filesystem=True,  # Always read-only filesystem
            allow_privilege_escalation=False,
            capabilities=k8s_client.V1Capabilities(drop=["ALL"]),
        )
        container.security_context.seccomp_profile = k8s_client.V1SeccompProfile(type="RuntimeDefault")
        container.stdin = False
        container.tty = False

        return container

    def _build_pod_spec(
        self, container: k8s_client.V1Container, command: CreatePodCommandEvent
    ) -> k8s_client.V1PodSpec:
        """Build pod specification"""
        execution_id = command.execution_id
        timeout = command.timeout_seconds or 300

        spec = k8s_client.V1PodSpec(
            containers=[container],
            restart_policy="Never",
            active_deadline_seconds=timeout,
            volumes=[
                k8s_client.V1Volume(
                    name="script-volume",
                    config_map=k8s_client.V1ConfigMapVolumeSource(
                        name=f"script-{execution_id}",
                        items=[k8s_client.V1KeyToPath(key=command.runtime_filename, path=command.runtime_filename)],
                    ),
                ),
                k8s_client.V1Volume(
                    name="entrypoint-volume",
                    config_map=k8s_client.V1ConfigMapVolumeSource(
                        name=f"script-{execution_id}",
                        items=[k8s_client.V1KeyToPath(key="entrypoint.sh", path="entrypoint.sh")],
                    ),
                ),
                k8s_client.V1Volume(
                    name="output-volume", empty_dir=k8s_client.V1EmptyDirVolumeSource(size_limit="10Mi")
                ),
                k8s_client.V1Volume(name="tmp-volume", empty_dir=k8s_client.V1EmptyDirVolumeSource(size_limit="10Mi")),
            ],
            # Critical security boundaries (not network-related)
            enable_service_links=False,  # Defense in depth - no service discovery
            automount_service_account_token=False,  # CRITICAL: No K8s API access
            host_network=False,  # CRITICAL: No host network namespace
            host_pid=False,  # CRITICAL: No host PID namespace
            host_ipc=False,  # CRITICAL: No host IPC namespace
        )

        spec.security_context = k8s_client.V1PodSecurityContext(
            run_as_non_root=True,  # Always run as non-root
            run_as_user=1000,
            run_as_group=1000,
            fs_group=1000,
            fs_group_change_policy="OnRootMismatch",
            seccomp_profile=k8s_client.V1SeccompProfile(type="RuntimeDefault"),
        )

        return spec

    def _build_pod_metadata(
        self,
        name: str,
        execution_id: str,
        user_id: str | None,
        language: str,
        correlation_id: str | None = None,
        saga_id: str | None = None,
    ) -> k8s_client.V1ObjectMeta:
        """Build pod metadata with correlation and saga tracking"""
        labels = {"app": "integr8s", "component": "executor", "execution-id": execution_id, "language": language}

        if user_id:
            labels["user-id"] = user_id[:63]  # K8s label value limit

        # Add correlation_id if provided (truncate to K8s label limit)
        if correlation_id:
            labels["correlation-id"] = correlation_id[:63]

        # Add saga_id if provided (truncate to K8s label limit)
        if saga_id:
            labels["saga-id"] = saga_id[:63]

        annotations = {
            "integr8s.io/execution-id": execution_id,
            "integr8s.io/created-by": "kubernetes-worker",
            "integr8s.io/language": language,
        }

        if correlation_id:
            annotations["integr8s.io/correlation-id"] = correlation_id

        if saga_id:
            annotations["integr8s.io/saga-id"] = saga_id

        return k8s_client.V1ObjectMeta(name=name, namespace=self.namespace, labels=labels, annotations=annotations)
