import pytest
from app.services.pod_manifest_builder import PodManifestBuilder


class TestPodManifestBuilder:
    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.builder = PodManifestBuilder(
            execution_id="test-execution-123",
            config_map_name="test-config-map",
            image="python:3.11-slim",
            command=["python", "/app/script.py"],
            pod_cpu_limit="1000m",
            pod_cpu_request="200m",
            pod_memory_limit="128Mi",
            pod_memory_request="128Mi",
            pod_execution_timeout=5,
            priority_class_name=None,
            namespace="default"
        )

    def test_pod_manifest_builder_initialization(self) -> None:
        assert self.builder is not None
        assert hasattr(self.builder, 'build')

    def test_build_execution_pod_manifest_python(self) -> None:
        manifest = self.builder.build()

        assert manifest is not None
        assert isinstance(manifest, dict)

        # Check basic pod structure
        assert "apiVersion" in manifest
        assert "kind" in manifest
        assert "metadata" in manifest
        assert "spec" in manifest

        assert manifest["kind"] == "Pod"
        assert manifest["apiVersion"] == "v1"

        # Check metadata
        metadata = manifest["metadata"]
        assert "name" in metadata
        assert "labels" in metadata
        assert "test-execution-123" in metadata["name"]

        # Check spec
        spec = manifest["spec"]
        assert "containers" in spec
        assert "restartPolicy" in spec
        assert spec["restartPolicy"] == "Never"

        # Check containers
        containers = spec["containers"]
        assert len(containers) >= 1

        main_container = containers[0]
        assert "name" in main_container
        assert "image" in main_container
        assert "command" in main_container

        # Check image is appropriate for Python
        assert "python" in main_container["image"].lower()

    def test_build_execution_pod_manifest_javascript(self) -> None:
        js_builder = PodManifestBuilder(
            execution_id="test-js-exec",
            config_map_name="test-js-config-map",
            image="node:18-slim",
            command=["node", "/app/script.js"],
            pod_cpu_limit="1000m",
            pod_cpu_request="200m",
            pod_memory_limit="128Mi",
            pod_memory_request="128Mi",
            pod_execution_timeout=5,
            priority_class_name=None,
            namespace="default"
        )

        manifest = js_builder.build()

        assert manifest is not None
        assert isinstance(manifest, dict)
        assert manifest["kind"] == "Pod"

        # Check container image is appropriate for JavaScript/Node.js
        containers = manifest["spec"]["containers"]
        main_container = containers[0]
        image = main_container["image"].lower()
        assert "node" in image

    def test_build_execution_pod_manifest_bash(self) -> None:
        bash_builder = PodManifestBuilder(
            execution_id="test-bash-exec",
            config_map_name="test-bash-config-map",
            image="bash:5.2",
            command=["bash", "/app/script.sh"],
            pod_cpu_limit="1000m",
            pod_cpu_request="200m",
            pod_memory_limit="128Mi",
            pod_memory_request="128Mi",
            pod_execution_timeout=5,
            priority_class_name=None,
            namespace="default"
        )

        manifest = bash_builder.build()

        assert manifest is not None
        assert isinstance(manifest, dict)
        assert manifest["kind"] == "Pod"

        # Check container image is appropriate for Bash
        containers = manifest["spec"]["containers"]
        main_container = containers[0]
        image = main_container["image"].lower()
        assert "bash" in image

    def test_pod_manifest_security_context(self) -> None:
        manifest = self.builder.build()

        # Check security context exists
        spec = manifest["spec"]

        # Should have security context at pod or container level
        has_pod_security = "securityContext" in spec

        containers = spec["containers"]
        has_container_security = any("securityContext" in container for container in containers)

        # Should have security context somewhere
        assert has_pod_security or has_container_security

    def test_pod_manifest_resource_limits(self) -> None:
        manifest = self.builder.build()

        containers = manifest["spec"]["containers"]
        main_container = containers[0]

        # Should have resource constraints
        if "resources" in main_container:
            resources = main_container["resources"]

            # Check for limits and/or requests
            assert "limits" in resources or "requests" in resources

            if "limits" in resources:
                limits = resources["limits"]
                # Should limit CPU and/or memory
                assert "cpu" in limits or "memory" in limits

    def test_pod_manifest_script_injection(self) -> None:
        manifest = self.builder.build()

        assert manifest is not None

        # The script should be properly handled/escaped
        containers = manifest["spec"]["containers"]
        main_container = containers[0]

        # Manifest should be properly structured
        assert "command" in main_container
        # Should handle scripts via mounted files, not direct injection
        assert "volumeMounts" in main_container

    def test_pod_manifest_unique_names(self) -> None:
        """Test that pod manifests have unique names."""
        builder1 = PodManifestBuilder(
            execution_id="test-unique-1",
            config_map_name="test-config-1",
            image="python:3.11-slim",
            command=["python", "/app/script.py"],
            pod_cpu_limit="1000m",
            pod_cpu_request="200m",
            pod_memory_limit="128Mi",
            pod_memory_request="128Mi",
            pod_execution_timeout=5,
            priority_class_name=None,
            namespace="default"
        )

        builder2 = PodManifestBuilder(
            execution_id="test-unique-2",
            config_map_name="test-config-2",
            image="python:3.11-slim",
            command=["python", "/app/script.py"],
            pod_cpu_limit="1000m",
            pod_cpu_request="200m",
            pod_memory_limit="128Mi",
            pod_memory_request="128Mi",
            pod_execution_timeout=5,
            priority_class_name=None,
            namespace="default"
        )

        manifest1 = builder1.build()
        manifest2 = builder2.build()

        name1 = manifest1["metadata"]["name"]
        name2 = manifest2["metadata"]["name"]

        assert name1 != name2
        assert "test-unique-1" in name1
        assert "test-unique-2" in name2

    def test_pod_manifest_labels(self) -> None:
        manifest = self.builder.build()

        metadata = manifest["metadata"]
        assert "labels" in metadata

        labels = metadata["labels"]

        # Should have app/component labels
        assert any(key in labels for key in ["app", "component", "role", "type"])

        # Should identify as execution pod
        label_values = " ".join(labels.values()).lower()
        assert any(term in label_values for term in ["execution", "runner", "script"])
