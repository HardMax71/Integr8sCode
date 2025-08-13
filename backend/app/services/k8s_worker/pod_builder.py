from typing import Any, Dict, List, Optional

from kubernetes import client as k8s_client

from app.runtime_registry import LANGUAGE_SPECS
from app.schemas_avro.event_schemas import ExecutionStartedEvent


class EventDrivenPodBuilder:
    """Builds Kubernetes pod manifests from execution events"""

    def __init__(self, namespace: str = "default"):
        self.namespace = namespace

    def build_pod_manifest(
            self,
            event: ExecutionStartedEvent,
            script_content: str,
            config: Dict[str, Any]
    ) -> k8s_client.V1Pod:
        """Build pod manifest from execution started event"""

        execution_id = str(event.execution_id)
        pod_name = event.pod_name
        # Get container image from config (passed from k8s worker)
        container_image = config.get("container_image")
        if not container_image:
            raise ValueError("container_image must be provided in config")

        # Extract language and version
        language, version = self._parse_container_image(container_image)

        # Get runtime info from LANGUAGE_SPECS
        language_spec = LANGUAGE_SPECS.get(language, {})
        if not language_spec:
            raise ValueError(f"Unsupported language: {language}")

        # Build container
        # Get the script file name
        file_extension = f".{language_spec.get('file_ext', 'txt')}"
        script_file = f"/script/script{file_extension}"

        # Build full command with entrypoint wrapper
        interpreter = language_spec.get("interpreter", ["sh"])
        # The entrypoint script will run the actual command
        full_command = ["/bin/sh", "/entry/entrypoint.sh"] + interpreter + [script_file]

        container = self._build_container(
            name="executor",
            image=container_image,
            command=full_command,
            language=language,
            config=config
        )

        # Build pod spec
        pod_spec = self._build_pod_spec(
            container=container,
            execution_id=execution_id,
            config=config
        )

        # Build pod metadata
        metadata = self._build_pod_metadata(
            name=pod_name,
            execution_id=execution_id,
            user_id=event.metadata.user_id,
            language=language
        )

        return k8s_client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=metadata,
            spec=pod_spec
        )

    def build_config_map(
            self,
            execution_id: str,
            script_content: str,
            entrypoint_content: str,
            language: str
    ) -> k8s_client.V1ConfigMap:
        """Build ConfigMap for script and entrypoint"""

        # Get file extension for script
        language_spec = LANGUAGE_SPECS.get(language, {})
        file_extension = f".{language_spec.get('file_ext', 'txt')}"

        return k8s_client.V1ConfigMap(
            api_version="v1",
            kind="ConfigMap",
            metadata=k8s_client.V1ObjectMeta(
                name=f"script-{execution_id}",
                namespace=self.namespace,
                labels={
                    "app": "integr8s",
                    "component": "execution-script",
                    "execution-id": execution_id
                }
            ),
            data={
                f"script{file_extension}": script_content,
                "entrypoint.sh": entrypoint_content
            }
        )

    def build_network_policy(
            self,
            execution_id: str,
            pod_name: str,
            allow_egress: bool = True
    ) -> k8s_client.V1NetworkPolicy:
        """Build NetworkPolicy for execution pod"""

        # Default: deny all ingress, allow DNS and HTTPS egress
        egress_rules = []

        if allow_egress:
            # Allow DNS
            egress_rules.append(
                k8s_client.V1NetworkPolicyEgressRule(
                    ports=[
                        k8s_client.V1NetworkPolicyPort(
                            protocol="UDP",
                            port=53
                        )
                    ]
                )
            )

            # Allow HTTPS
            egress_rules.append(
                k8s_client.V1NetworkPolicyEgressRule(
                    ports=[
                        k8s_client.V1NetworkPolicyPort(
                            protocol="TCP",
                            port=443
                        )
                    ]
                )
            )

        return k8s_client.V1NetworkPolicy(
            api_version="networking.k8s.io/v1",
            kind="NetworkPolicy",
            metadata=k8s_client.V1ObjectMeta(
                name=f"netpol-{execution_id}",
                namespace=self.namespace,
                labels={
                    "app": "integr8s",
                    "component": "network-policy",
                    "execution-id": execution_id
                }
            ),
            spec=k8s_client.V1NetworkPolicySpec(
                pod_selector=k8s_client.V1LabelSelector(
                    match_labels={
                        "execution-id": execution_id
                    }
                ),
                policy_types=["Ingress", "Egress"],
                ingress=[],  # Deny all ingress
                egress=egress_rules if egress_rules else []
            )
        )

    def _parse_container_image(self, image: str) -> tuple[str, str]:
        """Parse language and version from container image"""
        # Expected format: "python:3.9" or "registry.com/python:3.9"
        parts = image.split("/")[-1].split(":")
        if len(parts) == 2:
            return parts[0], parts[1]
        return parts[0], "latest"

    def _build_container(
            self,
            name: str,
            image: str,
            command: List[str],
            language: str,
            config: Dict[str, Any]
    ) -> k8s_client.V1Container:
        """Build container specification"""

        # Parse resource requirements from config
        cpu_request = config.get("default_cpu_request", "100m")
        memory_request = config.get("default_memory_request", "128Mi")

        # Limits are typically higher than requests
        cpu_limit = self._calculate_limit(cpu_request, factor=2.0)
        memory_limit = self._calculate_limit(memory_request, factor=2.0)

        container = k8s_client.V1Container(
            name=name,
            image=image,
            command=command,
            volume_mounts=[
                k8s_client.V1VolumeMount(
                    name="script-volume",
                    mount_path="/script"
                ),
                k8s_client.V1VolumeMount(
                    name="entrypoint-volume",
                    mount_path="/entry"
                ),
                k8s_client.V1VolumeMount(
                    name="output-volume",
                    mount_path="/output"
                ),
                k8s_client.V1VolumeMount(
                    name="tmp-volume",
                    mount_path="/tmp"
                )
            ],
            resources=k8s_client.V1ResourceRequirements(
                requests={
                    "cpu": cpu_request,
                    "memory": memory_request
                },
                limits={
                    "cpu": cpu_limit,
                    "memory": memory_limit
                }
            ),
            env=[
                k8s_client.V1EnvVar(
                    name="EXECUTION_ID",
                    value=config.get("execution_id", "")
                ),
                k8s_client.V1EnvVar(
                    name="OUTPUT_PATH",
                    value="/output"
                )
            ]
        )

        # Add security context if enabled
        if config.get("enable_security_context", True):
            container.security_context = k8s_client.V1SecurityContext(
                run_as_non_root=config.get("run_as_non_root", True),
                run_as_user=1000,
                run_as_group=1000,
                read_only_root_filesystem=config.get("read_only_root_filesystem", True),
                allow_privilege_escalation=False,
                capabilities=k8s_client.V1Capabilities(
                    drop=["ALL"]
                )
            )

        return container

    def _build_pod_spec(
            self,
            container: k8s_client.V1Container,
            execution_id: str,
            config: Dict[str, Any]
    ) -> k8s_client.V1PodSpec:
        """Build pod specification"""

        return k8s_client.V1PodSpec(
            containers=[container],
            restart_policy="Never",
            active_deadline_seconds=config.get("timeout_seconds", 300),
            volumes=[
                k8s_client.V1Volume(
                    name="script-volume",
                    config_map=k8s_client.V1ConfigMapVolumeSource(
                        name=f"script-{execution_id}",
                        items=[
                            k8s_client.V1KeyToPath(
                                key=self._get_script_key(config),
                                path="script" + config.get("file_extension", ".py")
                            )
                        ]
                    )
                ),
                k8s_client.V1Volume(
                    name="entrypoint-volume",
                    config_map=k8s_client.V1ConfigMapVolumeSource(
                        name=f"script-{execution_id}",
                        items=[
                            k8s_client.V1KeyToPath(
                                key="entrypoint.sh",
                                path="entrypoint.sh"
                            )
                        ]
                    )
                ),
                k8s_client.V1Volume(
                    name="output-volume",
                    empty_dir=k8s_client.V1EmptyDirVolumeSource(
                        size_limit="10Mi"
                    )
                ),
                k8s_client.V1Volume(
                    name="tmp-volume",
                    empty_dir=k8s_client.V1EmptyDirVolumeSource(
                        size_limit="10Mi"
                    )
                )
            ],
            security_context=k8s_client.V1PodSecurityContext(
                run_as_non_root=config.get("run_as_non_root", True),
                run_as_user=1000,
                run_as_group=1000,
                fs_group=1000
            ),
            dns_policy="ClusterFirst",
            enable_service_links=False,
            automount_service_account_token=False
        )

    def _build_pod_metadata(
            self,
            name: str,
            execution_id: str,
            user_id: Optional[str],
            language: str
    ) -> k8s_client.V1ObjectMeta:
        """Build pod metadata"""

        labels = {
            "app": "integr8s",
            "component": "executor",
            "execution-id": execution_id,
            "language": language
        }

        if user_id:
            labels["user-id"] = user_id[:63]  # K8s label value limit

        return k8s_client.V1ObjectMeta(
            name=name,
            namespace=self.namespace,
            labels=labels,
            annotations={
                "integr8s.io/execution-id": execution_id,
                "integr8s.io/created-by": "kubernetes-worker",
                "integr8s.io/language": language
            }
        )

    def _calculate_limit(self, request: str, factor: float) -> str:
        """Calculate resource limit from request"""
        # Parse the request value
        if request.endswith("m"):  # millicores
            value = int(request[:-1])
            return f"{int(value * factor)}m"
        elif request.endswith("Mi"):  # mebibytes
            value = int(request[:-2])
            return f"{int(value * factor)}Mi"
        elif request.endswith("Gi"):  # gibibytes
            value = int(request[:-2])
            return f"{value * factor:.1f}Gi"
        else:
            return request  # Return as-is if format unknown

    def _get_script_key(self, config: Dict[str, Any]) -> str:
        """Get the script key based on file extension in config"""
        # Common script file extensions
        script_extensions = [".py", ".js", ".ts", ".rb", ".go", ".java", ".cpp", ".c", ".rs", ".sh",
                             ".r", ".scala", ".kt", ".swift", ".php", ".pl", ".lua", ".jl", ".m", ".dart"]

        file_extension = config.get("file_extension", ".py")

        # Find matching script key in config map data
        for ext in script_extensions:
            if file_extension == ext:
                return f"script{ext}"

        # Default fallback
        return "script.py"
