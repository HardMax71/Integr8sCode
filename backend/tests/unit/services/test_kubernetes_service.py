import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from kubernetes.client.rest import ApiException

from app.services.kubernetes_service import (
    KubernetesService,
    KubernetesServiceError,
    KubernetesPodError,
    KubernetesConfigError
)
from tests.unit.services.mock_kubernetes_service import get_mock_kubernetes_service


class TestKubernetesExceptions:
    def test_kubernetes_service_error(self) -> None:
        error = KubernetesServiceError("Test error")

        assert isinstance(error, Exception)
        assert isinstance(error, KubernetesServiceError)
        assert str(error) == "Test error"

    def test_kubernetes_pod_error(self) -> None:
        error = KubernetesPodError("Pod error")

        assert isinstance(error, KubernetesServiceError)
        assert isinstance(error, KubernetesPodError)
        assert str(error) == "Pod error"

    def test_kubernetes_config_error(self) -> None:
        error = KubernetesConfigError("Config error")

        assert isinstance(error, KubernetesServiceError)
        assert isinstance(error, KubernetesConfigError)
        assert str(error) == "Config error"


# Removed TestKubernetesServiceManager class as KubernetesServiceManager no longer exists


class TestKubernetesServiceBasic:
    @pytest.fixture(autouse=True)
    async def setup(self) -> None:
        self.service = get_mock_kubernetes_service()

    def test_kubernetes_service_initialization(self) -> None:
        assert self.service is not None
        # manager attribute no longer exists
        assert hasattr(self.service, '_is_healthy')

    @pytest.mark.asyncio
    async def test_check_health_success(self) -> None:
        # Health check should succeed for mock service
        is_healthy = self.service.check_health()

        assert isinstance(is_healthy, bool)
        # Mock service should always be healthy
        assert is_healthy is True

    @pytest.mark.asyncio
    async def test_create_execution_pod_basic(self) -> None:
        execution_id = "test-exec-123"
        image = "python:3.11-slim"
        command = ["python", "/app/script.py"]
        config_map_data = {"script.py": "print('Hello from mock pod')"}

        # This should create a mock pod
        await self.service.create_execution_pod(
            execution_id=execution_id,
            image=image,
            command=command,
            config_map_data=config_map_data
        )

        # Check that pod was recorded in mock service
        assert execution_id in self.service._active_pods
        assert self.service._active_pods[execution_id]['image'] == image
        assert self.service._active_pods[execution_id]['command'] == command

    def test_service_configuration(self) -> None:
        service = self.service

        # Should have required configuration for mock service
        assert hasattr(service, 'NAMESPACE')

        # Configuration should be reasonable
        assert isinstance(service.NAMESPACE, str)
        assert len(service.NAMESPACE) > 0

    @pytest.mark.asyncio
    async def test_graceful_shutdown(self) -> None:
        # This should complete without error
        await self.service.graceful_shutdown()

        # Active pods should be cleared
        assert len(self.service._active_pods) == 0

    def test_service_dependencies(self) -> None:
        service = self.service

        # Mock service should have basic attributes
        assert hasattr(service, 'NAMESPACE')
        assert hasattr(service, '_is_healthy')
        assert hasattr(service, '_active_pods')


class TestKubernetesServiceDependency:
    def test_get_kubernetes_service_returns_instance(self) -> None:
        service = get_mock_kubernetes_service()

        assert service is not None
        assert hasattr(service, 'create_execution_pod')

    def test_get_kubernetes_service_singleton_behavior(self) -> None:
        service1 = get_mock_kubernetes_service()
        service2 = get_mock_kubernetes_service()

        # Should be different instances
        assert service1 is not service2
        assert hasattr(service1, 'create_execution_pod')
        assert hasattr(service2, 'create_execution_pod')

    def test_dependency_integration(self) -> None:
        """Test service integrates properly with dependency system."""
        service = get_mock_kubernetes_service()

        # Service should be properly initialized
        assert service is not None
        assert hasattr(service, 'create_execution_pod')


class TestKubernetesServiceConfiguration:
    @patch('app.services.kubernetes_service.k8s_config')
    @patch('os.path.exists')
    def test_setup_kubernetes_config_container_kubeconfig(self,
                                                          mock_exists: Mock,
                                                          mock_k8s_config: Mock) -> None:
        """Test using container kubeconfig path"""
        mock_exists.side_effect = lambda path: path == "/app/kubeconfig.yaml"

        with patch.object(KubernetesService, '_test_api_connection'):
            service = KubernetesService()
            mock_k8s_config.load_kube_config.assert_called_with(config_file="/app/kubeconfig.yaml")

    @patch('app.services.kubernetes_service.k8s_config')
    @patch('os.path.exists')
    def test_setup_kubernetes_config_incluster(self, mock_exists: Mock,
                                               mock_k8s_config: Mock) -> None:
        mock_exists.side_effect = lambda path: path == "/var/run/secrets/kubernetes.io/serviceaccount"

        with patch.object(KubernetesService, '_test_api_connection'):
            service = KubernetesService()
            mock_k8s_config.load_incluster_config.assert_called_once()

    @patch('app.services.kubernetes_service.get_settings')
    @patch('os.path.exists')
    def test_setup_kubernetes_config_default_path_not_exists(self,
                                                             mock_exists: Mock,
                                                             mock_get_settings: Mock) -> None:
        mock_settings = Mock()
        mock_settings.KUBERNETES_CONFIG_PATH = "~/.kube/config"
        mock_get_settings.return_value = mock_settings
        mock_exists.return_value = False

        with pytest.raises(KubernetesConfigError, match="Could not find valid Kubernetes configuration"):
            KubernetesService()

    @patch('app.services.kubernetes_service.get_settings')
    @patch('app.services.kubernetes_service.k8s_config')
    @patch('os.path.exists')
    @patch('os.path.expanduser')
    def test_setup_kubernetes_config_default_path_exists(self,
                                                         mock_expanduser: Mock,
                                                         mock_exists: Mock,
                                                         mock_k8s_config: Mock,
                                                         mock_get_settings: Mock) -> None:
        mock_settings = Mock()
        mock_settings.KUBERNETES_CONFIG_PATH = "~/.kube/config"
        mock_get_settings.return_value = mock_settings
        mock_expanduser.return_value = "/home/user/.kube/config"
        mock_exists.side_effect = lambda path: path == "/home/user/.kube/config"

        with patch.object(KubernetesService, '_test_api_connection'):
            service = KubernetesService()
            mock_k8s_config.load_kube_config.assert_called_with(config_file="/home/user/.kube/config")

    def test_test_api_connection_no_version_api(self) -> None:
        service = KubernetesService.__new__(KubernetesService)
        service.version_api = None

        with pytest.raises(KubernetesConfigError, match="VersionAPI client not initialized"):
            service._test_api_connection()

    def test_test_api_connection_api_error(self) -> None:
        service = KubernetesService.__new__(KubernetesService)
        mock_version_api = Mock()
        mock_version_api.get_code.side_effect = Exception("Connection failed")
        service.version_api = mock_version_api

        with pytest.raises(KubernetesConfigError, match="Unexpected error connecting to Kubernetes API"):
            service._test_api_connection()


class TestKubernetesServiceHealthChecks:
    @pytest.mark.asyncio
    async def test_check_health_no_version_api(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service.version_api = None

                result = await service.check_health()
                assert result is False
                assert service._is_healthy is False

    @pytest.mark.asyncio
    async def test_check_health_within_interval(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service.version_api = Mock()
                service._is_healthy = True
                service._last_health_check = datetime.now(timezone.utc)

                result = await service.check_health()
                assert result is True

    @pytest.mark.asyncio
    async def test_check_health_failure(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                mock_version_api = AsyncMock()
                mock_version_api.get_code.side_effect = Exception("API Error")
                service.version_api = mock_version_api
                service._last_health_check = datetime.now(timezone.utc) - timedelta(seconds=120)

                with patch('asyncio.to_thread', side_effect=Exception("API Error")):
                    result = await service.check_health()
                    assert result is False
                    assert service._is_healthy is False


class TestKubernetesServiceShutdown:
    @pytest.mark.asyncio
    async def test_graceful_shutdown_timeout(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service.SHUTDOWN_TIMEOUT = 0  # Force immediate timeout
                service._active_pods = {"execution-test": datetime.now(timezone.utc)}

                await service.graceful_shutdown()
                # Should complete without error despite timeout

    @pytest.mark.asyncio
    async def test_graceful_shutdown_non_execution_pod(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service._active_pods = {"other-pod": datetime.now(timezone.utc)}

                await service.graceful_shutdown()
                # Should return early for non-execution pods

    @pytest.mark.asyncio
    async def test_graceful_shutdown_cleanup_error(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service._active_pods = {"execution-test": datetime.now(timezone.utc)}

                with patch.object(service, '_cleanup_resources', side_effect=Exception("Cleanup failed")):
                    await service.graceful_shutdown()
                    # Should complete without raising despite cleanup error


class TestKubernetesServicePodOperations:
    @pytest.mark.asyncio
    async def test_create_execution_pod_circuit_breaker_open(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service.circuit_breaker.should_allow_request = Mock(return_value=False)

                with pytest.raises(KubernetesServiceError, match="Service circuit breaker is open"):
                    await service.create_execution_pod("test", "image:latest", ["echo", "test"], {})

    @pytest.mark.asyncio
    async def test_create_execution_pod_unhealthy_service(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service.circuit_breaker.should_allow_request = Mock(return_value=True)
                service.check_health = AsyncMock(return_value=False)

                with pytest.raises(KubernetesServiceError, match="Kubernetes service is unhealthy"):
                    await service.create_execution_pod("test", "image:latest", ["echo", "test"], {})

    @pytest.mark.asyncio
    async def test_create_execution_pod_creation_failure(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service.circuit_breaker.should_allow_request = Mock(return_value=True)
                service.check_health = AsyncMock(return_value=True)

                with patch('asyncio.to_thread', side_effect=Exception("Creation failed")):
                    with patch.object(service, '_cleanup_resources', new_callable=AsyncMock):
                        with pytest.raises(KubernetesPodError, match="Failed to create execution pod"):
                            await service.create_execution_pod("test", "image:latest", ["echo", "test"], {})

    @pytest.mark.asyncio
    async def test_wait_for_pod_completion_no_v1(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service.v1 = None

                with pytest.raises(KubernetesServiceError, match="Kubernetes client not initialized"):
                    await service._wait_for_pod_completion("test-pod")

    @pytest.mark.asyncio
    async def test_wait_for_pod_completion_timeout(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service.POD_RETRY_ATTEMPTS = 1
                mock_v1 = Mock()
                service.v1 = mock_v1

                # Mock pod that never completes
                mock_pod = Mock()
                mock_pod.status.phase = "Running"

                with patch('asyncio.to_thread', return_value=mock_pod):
                    with pytest.raises(KubernetesPodError, match="Timeout waiting for pod"):
                        await service._wait_for_pod_completion("test-pod")

    @pytest.mark.asyncio
    async def test_wait_for_pod_completion_api_exception_not_found(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service.POD_RETRY_ATTEMPTS = 1
                mock_v1 = Mock()
                service.v1 = mock_v1

                api_exception = ApiException(status=404, reason="Not Found")

                with patch('asyncio.to_thread', side_effect=api_exception):
                    with pytest.raises(KubernetesPodError, match="Timeout waiting for pod"):
                        await service._wait_for_pod_completion("test-pod")

    @pytest.mark.asyncio
    async def test_wait_for_pod_completion_api_exception_other(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service.POD_RETRY_ATTEMPTS = 1
                mock_v1 = Mock()
                service.v1 = mock_v1

                api_exception = ApiException(status=500, reason="Internal Server Error")

                with patch('asyncio.to_thread', side_effect=api_exception):
                    with pytest.raises(KubernetesPodError, match="Timeout waiting for pod"):
                        await service._wait_for_pod_completion("test-pod")


class TestKubernetesServiceLogging:
    @pytest.mark.asyncio
    async def test_get_container_logs_no_v1(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service.v1 = None

                result = await service._get_container_logs("test-pod", "container")
                assert "Kubernetes client not initialized" in result

    @pytest.mark.asyncio
    async def test_get_container_logs_api_exception(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                mock_v1 = Mock()
                service.v1 = mock_v1

                api_exception = ApiException(status=500, reason="Server Error")

                with patch('asyncio.to_thread', side_effect=api_exception):
                    result = await service._get_container_logs("test-pod", "container")
                    assert "Error retrieving logs: Server Error" in result


class TestKubernetesServiceConfigMaps:
    @pytest.mark.asyncio
    async def test_create_config_map_no_v1(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service.v1 = None

                mock_config_map = Mock()
                mock_config_map.metadata.name = "test-cm"

                with pytest.raises(KubernetesServiceError, match="Kubernetes client not initialized"):
                    await service._create_config_map(mock_config_map)

    @pytest.mark.asyncio
    async def test_create_config_map_api_exception(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                mock_v1 = Mock()
                service.v1 = mock_v1

                mock_config_map = Mock()
                mock_config_map.metadata.name = "test-cm"

                api_exception = ApiException(status=409, reason="Conflict")

                with patch('asyncio.to_thread', side_effect=api_exception):
                    with pytest.raises(KubernetesServiceError, match="Failed to create ConfigMap"):
                        await service._create_config_map(mock_config_map)


class TestKubernetesServicePodCreation:
    @pytest.mark.asyncio
    async def test_create_namespaced_pod_no_v1(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service.v1 = None

                pod_manifest = {"metadata": {"name": "test-pod"}}

                with pytest.raises(KubernetesPodError, match="Kubernetes client not initialized"):
                    await service._create_namespaced_pod(pod_manifest)

    @pytest.mark.asyncio
    async def test_create_namespaced_pod_api_exception(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                mock_v1 = Mock()
                service.v1 = mock_v1

                pod_manifest = {"metadata": {"name": "test-pod"}}
                api_exception = ApiException(status=400, reason="Bad Request")

                with patch('asyncio.to_thread', side_effect=api_exception):
                    with pytest.raises(KubernetesPodError, match="Failed to create pod"):
                        await service._create_namespaced_pod(pod_manifest)


class TestKubernetesServiceCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_resources_no_v1(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service.v1 = None

                # Should not raise error when v1 is None
                await service._cleanup_resources("test-pod", "test-cm")

    @pytest.mark.asyncio
    async def test_cleanup_resources_api_exceptions(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                mock_v1 = Mock()
                service.v1 = mock_v1

                api_exception = ApiException(status=404, reason="Not Found")

                with patch('asyncio.to_thread', side_effect=api_exception):
                    with patch.object(service, '_delete_network_policy', new_callable=AsyncMock):
                        # Should not raise error despite API exceptions
                        await service._cleanup_resources("test-pod", "test-cm", "test-execution")


class TestKubernetesServiceNetworkPolicies:
    @pytest.mark.asyncio
    async def test_create_network_policy_no_networking_v1(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service.networking_v1 = None

                policy_manifest = {"metadata": {"name": "test-policy"}}

                with pytest.raises(KubernetesServiceError, match="NetworkingV1Api client not initialized"):
                    await service._create_network_policy(policy_manifest)

    @pytest.mark.asyncio
    async def test_create_network_policy_api_exception(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                mock_networking_v1 = Mock()
                service.networking_v1 = mock_networking_v1

                policy_manifest = {"metadata": {"name": "test-policy"}}
                api_exception = ApiException(status=400, reason="Bad Request")

                with patch('asyncio.to_thread', side_effect=api_exception):
                    with pytest.raises(KubernetesServiceError, match="Failed to create NetworkPolicy"):
                        await service._create_network_policy(policy_manifest)

    @pytest.mark.asyncio
    async def test_delete_network_policy_no_networking_v1(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service.networking_v1 = None

                # Should not raise error when networking_v1 is None
                await service._delete_network_policy("test-policy")

    @pytest.mark.asyncio
    async def test_delete_network_policy_api_exception(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                mock_networking_v1 = Mock()
                service.networking_v1 = mock_networking_v1

                api_exception = ApiException(status=404, reason="Not Found")

                with patch('asyncio.to_thread', side_effect=api_exception):
                    # Should not raise error despite API exception
                    await service._delete_network_policy("test-policy")


class TestKubernetesServiceDaemonSets:
    @pytest.mark.asyncio
    async def test_ensure_image_pre_puller_daemonset_no_apps_v1(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                service.apps_v1 = None

                # Should not raise error when apps_v1 is None
                await service.ensure_image_pre_puller_daemonset()

    @pytest.mark.asyncio
    async def test_ensure_image_pre_puller_daemonset_exists_replace(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                mock_apps_v1 = Mock()
                service.apps_v1 = mock_apps_v1

                with patch('asyncio.sleep'):
                    with patch('app.services.kubernetes_service.RUNTIME_REGISTRY', {}):
                        with patch('asyncio.to_thread') as mock_to_thread:
                            # First call succeeds (DaemonSet exists), second call is replace
                            mock_to_thread.side_effect = [Mock(), Mock()]

                            await service.ensure_image_pre_puller_daemonset()

    @pytest.mark.asyncio
    async def test_ensure_image_pre_puller_daemonset_not_found_create(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                mock_apps_v1 = Mock()
                service.apps_v1 = mock_apps_v1

                api_exception_404 = ApiException(status=404, reason="Not Found")

                with patch('asyncio.sleep'):
                    with patch('app.services.kubernetes_service.RUNTIME_REGISTRY', {}):
                        with patch('asyncio.to_thread') as mock_to_thread:
                            # First call raises 404, second call is create
                            mock_to_thread.side_effect = [api_exception_404, Mock()]

                            await service.ensure_image_pre_puller_daemonset()

    @pytest.mark.asyncio
    async def test_ensure_image_pre_puller_daemonset_api_error(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                mock_apps_v1 = Mock()
                service.apps_v1 = mock_apps_v1

                api_exception = ApiException(status=500, reason="Server Error")

                with patch('asyncio.sleep'):
                    with patch('app.services.kubernetes_service.RUNTIME_REGISTRY', {}):
                        with patch('asyncio.to_thread', side_effect=api_exception):
                            # Should not raise error despite API exception
                            await service.ensure_image_pre_puller_daemonset()

    @pytest.mark.asyncio
    async def test_ensure_image_pre_puller_daemonset_general_error(self) -> None:
        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                service = KubernetesService()
                mock_apps_v1 = Mock()
                service.apps_v1 = mock_apps_v1

                with patch('asyncio.sleep'):
                    with patch('app.services.kubernetes_service.RUNTIME_REGISTRY', {}):
                        with patch('asyncio.to_thread', side_effect=Exception("Unexpected error")):
                            # Should not raise error despite general exception
                            await service.ensure_image_pre_puller_daemonset()


class TestKubernetesDependencyFunctions:
    def test_get_kubernetes_service(self) -> None:
        """Test that get_kubernetes_service returns a KubernetesService instance"""
        from app.core.service_dependencies import get_kubernetes_service
        from app.services.kafka_event_service import KafkaEventService

        mock_event_service = Mock(spec=KafkaEventService)

        with patch('app.services.kubernetes_service.get_settings'):
            with patch.object(KubernetesService, '_initialize_kubernetes_client'):
                result = asyncio.run(get_kubernetes_service(mock_event_service))

                assert isinstance(result, KubernetesService)
                assert hasattr(result, 'set_event_service')
                # Verify event service was set
                assert result._event_service == mock_event_service
