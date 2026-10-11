from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from kubernetes_asyncio import client as k8s_client

from app.domain.enums import QueuePriority
from app.domain.events import CreatePodCommandEvent, EventMetadata
from app.runtime_registry import LANGUAGE_SPECS, POD_RUNTIME_CONFIGS, RUNTIME_REGISTRY
from app.services.k8s_worker import PodBuilder

pytestmark = pytest.mark.unit


class TestPodBuilder:
    """Test PodBuilder functionality."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings with K8s config values."""
        settings = MagicMock()
        settings.K8S_NAMESPACE = "integr8scode"
        settings.K8S_POD_CPU_REQUEST = "100m"
        settings.K8S_POD_MEMORY_REQUEST = "128Mi"
        settings.K8S_POD_CPU_LIMIT = "500m"
        settings.K8S_POD_MEMORY_LIMIT = "512Mi"
        return settings

    @pytest.fixture
    def pod_builder(self, mock_settings: MagicMock) -> PodBuilder:
        """Create PodBuilder instance."""
        return PodBuilder(settings=mock_settings)

    @pytest.fixture
    def create_pod_command(self) -> CreatePodCommandEvent:
        """Create sample pod command event."""
        return CreatePodCommandEvent(
            execution_id=str(uuid4()),
            saga_id=str(uuid4()),
            script="print('hello world')",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_filename="script.py",
            runtime_command=["python", "/scripts/script.py"],
            timeout_seconds=300,
            cpu_request="200m",
            memory_request="256Mi",
            cpu_limit="1000m",
            memory_limit="1Gi",
            priority=QueuePriority.NORMAL,
            metadata=EventMetadata(user_id=str(uuid4()), service_name="test-service", service_version="1.0.0"),
        )

    def test_build_pod_manifest(self, pod_builder: PodBuilder, create_pod_command: CreatePodCommandEvent) -> None:
        """Test building pod manifest."""
        pod = pod_builder.build_pod_manifest(create_pod_command)

        # Verify basic pod structure
        assert isinstance(pod, k8s_client.V1Pod)
        assert pod.api_version == "v1"
        assert pod.kind == "Pod"

        # Verify metadata
        assert pod.metadata.name == f"executor-{create_pod_command.execution_id}"
        assert pod.metadata.namespace == "integr8scode"
        assert pod.metadata.labels["app"] == "integr8s"
        assert pod.metadata.labels["component"] == "executor"
        assert pod.metadata.labels["execution-id"] == create_pod_command.execution_id
        assert pod.metadata.labels["language"] == "python"

        # Verify annotations
        assert pod.metadata.annotations["integr8s.io/execution-id"] == create_pod_command.execution_id
        assert pod.metadata.annotations["integr8s.io/saga-id"] == create_pod_command.saga_id

    def test_build_pod_spec_security(self, pod_builder: PodBuilder, create_pod_command: CreatePodCommandEvent) -> None:
        """Test pod security settings."""
        pod = pod_builder.build_pod_manifest(create_pod_command)
        spec = pod.spec

        # Verify pod-level security
        assert spec.security_context.run_as_non_root is True
        assert spec.security_context.run_as_user == 1000
        assert spec.security_context.run_as_group == 1000
        assert spec.security_context.fs_group == 1000
        assert spec.security_context.seccomp_profile.type == "RuntimeDefault"

        # Verify critical security boundaries
        assert spec.enable_service_links is False
        assert spec.automount_service_account_token is False
        assert spec.host_network is False
        assert spec.host_pid is False
        assert spec.host_ipc is False

    def test_container_security_context(
        self, pod_builder: PodBuilder, create_pod_command: CreatePodCommandEvent
    ) -> None:
        """Test container security context."""
        pod = pod_builder.build_pod_manifest(create_pod_command)
        container = pod.spec.containers[0]

        # Verify container security
        assert container.security_context.run_as_non_root is True
        assert container.security_context.run_as_user == 1000
        assert container.security_context.run_as_group == 1000
        assert container.security_context.read_only_root_filesystem is True
        assert container.security_context.allow_privilege_escalation is False
        assert container.security_context.capabilities.drop == ["ALL"]
        assert container.security_context.seccomp_profile.type == "RuntimeDefault"

        # Verify interactive features disabled
        assert container.stdin is False
        assert container.tty is False

    def test_container_resources(self, pod_builder: PodBuilder, create_pod_command: CreatePodCommandEvent) -> None:
        """Test container resource limits."""
        pod = pod_builder.build_pod_manifest(create_pod_command)
        container = pod.spec.containers[0]

        # Verify resources from command
        assert container.resources.requests["cpu"] == "200m"
        assert container.resources.requests["memory"] == "256Mi"
        assert container.resources.limits["cpu"] == "1000m"
        assert container.resources.limits["memory"] == "1Gi"

    def test_container_resources_defaults(self, pod_builder: PodBuilder, mock_settings: MagicMock) -> None:
        """Test container resource defaults."""
        command = CreatePodCommandEvent(
            execution_id=str(uuid4()),
            saga_id=str(uuid4()),
            script="print('hello')",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_filename="script.py",
            runtime_command=["python", "/scripts/script.py"],
            # No resource specifications - should use defaults
            timeout_seconds=300,
            cpu_request="",
            memory_request="",
            cpu_limit="",
            memory_limit="",
            priority=QueuePriority.NORMAL,
            metadata=EventMetadata(
                service_name="svc",
                service_version="1",
                user_id=str(uuid4()),
            ),
        )

        pod = pod_builder.build_pod_manifest(command)
        container = pod.spec.containers[0]

        # Verify default resources from settings
        assert container.resources.requests["cpu"] == mock_settings.K8S_POD_CPU_REQUEST
        assert container.resources.requests["memory"] == mock_settings.K8S_POD_MEMORY_REQUEST
        assert container.resources.limits["cpu"] == mock_settings.K8S_POD_CPU_LIMIT
        assert container.resources.limits["memory"] == mock_settings.K8S_POD_MEMORY_LIMIT

    def test_pod_volumes(self, pod_builder: PodBuilder, create_pod_command: CreatePodCommandEvent) -> None:
        """Test pod volume configuration."""
        pod = pod_builder.build_pod_manifest(create_pod_command)
        volumes = {v.name: v for v in pod.spec.volumes}

        # Verify all required volumes
        assert "script-volume" in volumes
        assert "entrypoint-volume" in volumes
        assert "output-volume" in volumes
        assert "tmp-volume" in volumes

        # Verify ConfigMap volumes
        script_vol = volumes["script-volume"]
        assert script_vol.config_map.name == f"script-{create_pod_command.execution_id}"
        assert script_vol.config_map.items[0].key == "script.py"

        entrypoint_vol = volumes["entrypoint-volume"]
        assert entrypoint_vol.config_map.name == f"script-{create_pod_command.execution_id}"
        assert entrypoint_vol.config_map.items[0].key == "entrypoint.sh"

        # Verify EmptyDir volumes with size limits
        output_vol = volumes["output-volume"]
        assert output_vol.empty_dir.size_limit == "10Mi"

        tmp_vol = volumes["tmp-volume"]
        assert tmp_vol.empty_dir.size_limit == "10Mi"

    def test_container_volume_mounts(self, pod_builder: PodBuilder, create_pod_command: CreatePodCommandEvent) -> None:
        """Test container volume mounts."""
        pod = pod_builder.build_pod_manifest(create_pod_command)
        container = pod.spec.containers[0]
        mounts = {m.name: m for m in container.volume_mounts}

        # Verify all mounts
        assert mounts["script-volume"].mount_path == "/scripts"
        assert mounts["script-volume"].read_only is True

        assert mounts["entrypoint-volume"].mount_path == "/entry"
        assert mounts["entrypoint-volume"].read_only is True

        assert mounts["output-volume"].mount_path == "/output"
        assert mounts["output-volume"].read_only is None  # Writable

        assert mounts["tmp-volume"].mount_path == "/tmp"
        assert mounts["tmp-volume"].read_only is None  # Writable

    def test_build_config_map(self, pod_builder: PodBuilder, create_pod_command: CreatePodCommandEvent) -> None:
        """Test ConfigMap creation."""
        script_content = "print('hello world')"
        entrypoint_content = "#!/bin/sh\nexec $@"

        config_map = pod_builder.build_config_map(create_pod_command, script_content, entrypoint_content)

        # Verify ConfigMap structure
        assert isinstance(config_map, k8s_client.V1ConfigMap)
        assert config_map.api_version == "v1"
        assert config_map.kind == "ConfigMap"

        # Verify metadata
        assert config_map.metadata.name == f"script-{create_pod_command.execution_id}"
        assert config_map.metadata.namespace == "integr8scode"
        assert config_map.metadata.labels["execution-id"] == create_pod_command.execution_id
        assert config_map.metadata.labels["saga-id"] == create_pod_command.saga_id

        # Verify data
        assert config_map.data["script.py"] == script_content
        assert config_map.data["entrypoint.sh"] == entrypoint_content

    def test_pod_timeout_configuration(
        self, pod_builder: PodBuilder, create_pod_command: CreatePodCommandEvent
    ) -> None:
        """Test pod timeout configuration."""
        pod = pod_builder.build_pod_manifest(create_pod_command)

        # Verify active deadline is set
        assert pod.spec.active_deadline_seconds == 300

    def test_pod_timeout_default(
        self,
        pod_builder: PodBuilder,
    ) -> None:
        """Test default pod timeout."""
        command = CreatePodCommandEvent(
            execution_id=str(uuid4()),
            saga_id=str(uuid4()),
            script="print('hello')",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_filename="script.py",
            runtime_command=["python"],
            # No timeout specified, use falsy 0 to trigger default
            timeout_seconds=0,
            cpu_request="100m",
            memory_request="128Mi",
            cpu_limit="500m",
            memory_limit="512Mi",
            priority=QueuePriority.NORMAL,
            metadata=EventMetadata(user_id=str(uuid4()), service_name="t", service_version="1"),
        )

        pod = pod_builder.build_pod_manifest(command)

        # Default timeout should be 300 seconds
        assert pod.spec.active_deadline_seconds == 300

    def test_container_command(self, pod_builder: PodBuilder, create_pod_command: CreatePodCommandEvent) -> None:
        """Test container command construction."""
        pod = pod_builder.build_pod_manifest(create_pod_command)
        container = pod.spec.containers[0]

        # Verify command
        expected_command = ["/bin/sh", "/entry/entrypoint.sh", "python", "/scripts/script.py"]
        assert container.command == expected_command

    def test_container_environment(self, pod_builder: PodBuilder, create_pod_command: CreatePodCommandEvent) -> None:
        """Test container environment variables."""
        pod = pod_builder.build_pod_manifest(create_pod_command)
        container = pod.spec.containers[0]

        env_vars = {e.name: e.value for e in container.env}

        assert env_vars["EXECUTION_ID"] == create_pod_command.execution_id
        assert env_vars["OUTPUT_PATH"] == "/output"

    def test_pod_labels_truncation(
        self,
        pod_builder: PodBuilder,
    ) -> None:
        """Test label value truncation for K8s limits."""
        long_id = "a" * 100  # Exceeds K8s 63 char limit

        command = CreatePodCommandEvent(
            execution_id=long_id,
            saga_id=long_id,
            script="print('test')",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_filename="script.py",
            runtime_command=["python"],
            timeout_seconds=300,
            cpu_limit="100m",
            memory_limit="128Mi",
            cpu_request="50m",
            memory_request="64Mi",
            priority=QueuePriority.NORMAL,
            metadata=EventMetadata(
                service_name="svc",
                service_version="1",
                user_id=long_id,
            ),
        )

        pod = pod_builder.build_pod_manifest(command)

        # Verify labels are truncated to 63 chars
        assert len(pod.metadata.labels["user-id"]) == 63
        assert len(pod.metadata.labels["saga-id"]) == 63

        # But annotations should have full values
        assert pod.metadata.annotations["integr8s.io/saga-id"] == long_id

    def test_pod_restart_policy(self, pod_builder: PodBuilder, create_pod_command: CreatePodCommandEvent) -> None:
        """Test pod restart policy."""
        pod = pod_builder.build_pod_manifest(create_pod_command)

        # Should never restart (one-shot execution)
        assert pod.spec.restart_policy == "Never"

    def test_different_languages(
        self,
        pod_builder: PodBuilder,
    ) -> None:
        """Test pod creation for different languages."""
        languages = [
            ("python", "python:3.11-slim", "script.py", ["python", "/scripts/script.py"]),
            ("node", "node:18-slim", "script.js", ["node", "/scripts/script.js"]),
            ("bash", "alpine:latest", "script.sh", ["sh", "/scripts/script.sh"]),
        ]

        for language, image, filename, command in languages:
            cmd = CreatePodCommandEvent(
                execution_id=str(uuid4()),
                saga_id=str(uuid4()),
                script=f"# {language} script",
                language=language,
                language_version="1.0",
                runtime_image=image,
                runtime_filename=filename,
                runtime_command=command,
                timeout_seconds=300,
                cpu_request="100m",
                memory_request="128Mi",
                cpu_limit="200m",
                memory_limit="256Mi",
                priority=QueuePriority.NORMAL,
                metadata=EventMetadata(user_id=str(uuid4()), service_name="t", service_version="1"),
            )

            pod = pod_builder.build_pod_manifest(cmd)

            assert pod.metadata.labels["language"] == language
            assert pod.metadata.annotations["integr8s.io/language"] == language
            assert pod.spec.containers[0].image == image


def _runtime_command(
    language: str, *, cpu_limit: str, memory_limit: str, timeout_seconds: int
) -> CreatePodCommandEvent:
    version = LANGUAGE_SPECS[language]["versions"][0]
    runtime = RUNTIME_REGISTRY[language][version]
    return CreatePodCommandEvent(
        execution_id=str(uuid4()),
        saga_id=str(uuid4()),
        script="x",
        language=language,
        language_version=version,
        runtime_image=runtime.image,
        runtime_filename=runtime.file_name,
        runtime_command=runtime.command,
        timeout_seconds=timeout_seconds,
        cpu_request="200m",
        memory_request="128Mi",
        cpu_limit=cpu_limit,
        memory_limit=memory_limit,
        metadata=EventMetadata(user_id=str(uuid4()), service_name="t", service_version="1"),
    )


@pytest.fixture
def builder() -> PodBuilder:
    settings = MagicMock()
    settings.K8S_NAMESPACE = "integr8scode"
    settings.K8S_POD_RUNTIME_CLASS_NAME = None
    return PodBuilder(settings=settings)


@pytest.mark.parametrize("language", [lang for lang, spec in LANGUAGE_SPECS.items() if "pod" not in spec])
def test_languages_without_pod_settings_keep_the_configured_pod(builder: PodBuilder, language: str) -> None:
    command = _runtime_command(language, cpu_limit="100m", memory_limit="64Mi", timeout_seconds=5)

    pod = builder.build_pod_manifest(command)
    container = pod.spec.containers[0]
    volumes = {v.name: v for v in pod.spec.volumes}

    assert container.command == ["/bin/sh", "/entry/entrypoint.sh", *command.runtime_command]
    assert container.resources.limits == {"cpu": "100m", "memory": "64Mi"}
    assert container.resources.requests == {"cpu": "200m", "memory": "128Mi"}
    assert {e.name: e.value for e in container.env} == {
        "EXECUTION_ID": command.execution_id,
        "OUTPUT_PATH": "/output",
    }
    assert volumes["tmp-volume"].empty_dir.size_limit == "10Mi"
    assert volumes["output-volume"].empty_dir.size_limit == "10Mi"
    assert pod.spec.active_deadline_seconds == 5


def test_go_pod_gets_its_cache_env_and_raised_minimums(builder: PodBuilder) -> None:
    command = _runtime_command("go", cpu_limit="500m", memory_limit="128Mi", timeout_seconds=5)

    pod = builder.build_pod_manifest(command)
    container = pod.spec.containers[0]
    volumes = {v.name: v for v in pod.spec.volumes}

    assert container.command == [
        "/bin/sh",
        "/entry/entrypoint.sh",
        "sh",
        "-c",
        'go build -o /tmp/main -ldflags="-s -w" -gcflags=all=-dwarf=false "$0" && exec /tmp/main',
        "/scripts/main.go",
    ]
    assert {e.name: e.value for e in container.env} == {
        "EXECUTION_ID": command.execution_id,
        "OUTPUT_PATH": "/output",
        "HOME": "/tmp",
        "GOCACHE": "/tmp/go-cache",
    }
    assert container.resources.limits == {"cpu": "1000m", "memory": "320Mi"}
    assert container.resources.requests == {"cpu": "200m", "memory": "128Mi"}
    assert volumes["tmp-volume"].empty_dir.size_limit == "64Mi"
    assert volumes["output-volume"].empty_dir.size_limit == "10Mi"
    assert pod.spec.active_deadline_seconds == 30
    assert container.security_context.read_only_root_filesystem is True


def test_go_pod_keeps_configured_limits_above_the_minimums(builder: PodBuilder) -> None:
    command = _runtime_command("go", cpu_limit="2", memory_limit="1Gi", timeout_seconds=120)

    pod = builder.build_pod_manifest(command)

    assert pod.spec.containers[0].resources.limits == {"cpu": "2", "memory": "1Gi"}
    assert pod.spec.active_deadline_seconds == 120


@pytest.mark.parametrize(
    ("cpu_limit", "memory_limit", "expected"),
    [
        ("1", "320Mi", {"cpu": "1", "memory": "320Mi"}),
        ("0.5", "300M", {"cpu": "1000m", "memory": "320Mi"}),
        ("1500m", "400M", {"cpu": "1500m", "memory": "400M"}),
        ("999m", "1Gi", {"cpu": "1000m", "memory": "1Gi"}),
    ],
)
def test_minimums_compare_quantities_across_units(
    builder: PodBuilder, cpu_limit: str, memory_limit: str, expected: dict[str, str]
) -> None:
    command = _runtime_command("go", cpu_limit=cpu_limit, memory_limit=memory_limit, timeout_seconds=60)

    assert builder.build_pod_manifest(command).spec.containers[0].resources.limits == expected


def test_unparseable_limit_is_rejected_when_a_minimum_applies(builder: PodBuilder) -> None:
    command = _runtime_command("go", cpu_limit="lots", memory_limit="512Mi", timeout_seconds=60)

    with pytest.raises(ValueError, match="Unsupported resource quantity: 'lots'"):
        builder.build_pod_manifest(command)


def test_unknown_language_falls_back_to_default_pod_settings(builder: PodBuilder) -> None:
    command = _runtime_command("python", cpu_limit="100m", memory_limit="64Mi", timeout_seconds=5)
    command = command.model_copy(update={"language": "cobol"})

    pod = builder.build_pod_manifest(command)
    volumes = {v.name: v for v in pod.spec.volumes}

    assert "cobol" not in POD_RUNTIME_CONFIGS
    assert volumes["tmp-volume"].empty_dir.size_limit == "10Mi"
    assert pod.spec.containers[0].resources.limits == {"cpu": "100m", "memory": "64Mi"}
