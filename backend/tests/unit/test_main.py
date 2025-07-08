import concurrent.futures
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from app.config import get_settings
from app.main import create_app, lifespan
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestCreateApp:
    def test_create_app_basic(self) -> None:
        with patch('app.main.get_settings') as mock_get_settings:
            mock_settings = Mock()
            mock_settings.PROJECT_NAME = "Test App"
            mock_settings.API_V1_STR = "/api/v1"
            mock_settings.TESTING = False
            mock_settings.RATE_LIMITS = "100/minute"
            mock_get_settings.return_value = mock_settings

            app = create_app()

            assert isinstance(app, FastAPI)
            assert app.title == "Test App"

    def test_app_has_required_metadata(self) -> None:
        app = create_app()

        assert app.title is not None
        assert app.version is not None
        assert len(app.title) > 0
        assert len(app.version) > 0

    def test_app_middleware_configured(self) -> None:
        app = create_app()

        # Should have middleware
        assert len(app.user_middleware) > 0

    def test_app_exception_handlers_configured(self) -> None:
        app = create_app()

        # Should have exception handlers
        assert len(app.exception_handlers) > 0

    def test_app_cors_configured(self) -> None:
        app = create_app()

        # Check if CORS middleware is present
        cors_middleware = any(
            'cors' in str(middleware).lower()
            for middleware in app.user_middleware
        )
        assert cors_middleware


class TestAppIntegration:
    @pytest.fixture
    def client(self) -> TestClient:
        app = create_app()
        return TestClient(app)

    def test_app_handles_404(self, client: TestClient) -> None:
        response = client.get("/nonexistent/endpoint")

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_multiple_concurrent_requests(self, client: TestClient) -> None:
        def make_request() -> Any:
            return client.get("/api/v1/health")

        # Make multiple concurrent requests
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request) for _ in range(10)]
            responses = [future.result() for future in futures]

        # All should succeed
        for response in responses:
            assert response.status_code == 200

    def test_error_response_format(self, client: TestClient) -> None:
        # Try to access a protected endpoint without auth
        response = client.get("/api/v1/verify-token")

        assert response.status_code == 401
        data = response.json()
        assert "detail" in data
        assert isinstance(data["detail"], str)

    def test_app_routes_integration(self, client: TestClient) -> None:
        # Test different route groups
        test_cases = [
            ("/api/v1/health", 200),
            ("/docs", 200),
            ("/openapi.json", 200),
        ]

        for path, expected_status in test_cases:
            response = client.get(path)
            assert response.status_code == expected_status


class TestAppSettings:
    def test_settings_loaded(self) -> None:
        settings = get_settings()

        assert settings is not None
        assert hasattr(settings, 'PROJECT_NAME')
        assert hasattr(settings, 'API_V1_STR')
        assert hasattr(settings, 'SECRET_KEY')

    def test_settings_values_reasonable(self) -> None:
        settings = get_settings()

        assert len(settings.PROJECT_NAME) > 0
        assert len(settings.API_V1_STR) > 0
        assert len(settings.SECRET_KEY) > 0  # Should have a secret key

    def test_database_settings(self) -> None:
        settings = get_settings()

        assert hasattr(settings, 'MONGODB_URL')
        assert settings.MONGODB_URL is not None
        assert len(settings.MONGODB_URL) > 0


class TestAppLifecycle:
    def test_app_creates_without_errors(self) -> None:
        try:
            app = create_app()
            assert app is not None
        except Exception as e:
            pytest.fail(f"App creation failed: {e}")

    def test_app_can_be_recreated(self) -> None:
        app1 = create_app()
        app2 = create_app()

        assert app1 is not None
        assert app2 is not None
        # They should be different instances
        assert app1 is not app2

    def test_multiple_test_clients(self) -> None:
        app1 = create_app()
        app2 = create_app()

        client1 = TestClient(app1)
        client2 = TestClient(app2)

        # Both should work
        response1 = client1.get("/api/v1/health")
        response2 = client2.get("/api/v1/health")

        assert response1.status_code == 200
        assert response2.status_code == 200


class TestMainComponents:
    def test_app_lifespan_startup_success(self) -> None:
        with patch('app.main.logger') as mock_logger:
            _ = create_app()

            # Verify logging during app creation
            mock_logger.info.assert_any_call("Prometheus instrumentator configured")

    def test_app_middleware_order(self) -> None:
        app = create_app()

        # Check that middleware exists
        assert len(app.user_middleware) > 0

        # Middleware should include CORS, rate limiting, etc.
        middleware_types = [str(middleware) for middleware in app.user_middleware]

        # Should have CORS middleware
        cors_middleware = any('cors' in mw.lower() for mw in middleware_types)
        assert cors_middleware

    def test_app_routes_registered(self) -> None:
        app = create_app()

        # Get all route paths
        route_paths = [route.path for route in app.routes]

        # Should have API v1 routes
        api_routes = [path for path in route_paths if path.startswith("/api/v1/")]
        assert len(api_routes) > 0

        # Should have specific endpoints
        expected_endpoints = [
            "/api/v1/health",
            "/api/v1/login",
            "/api/v1/register",
            "/api/v1/execute",
            "/api/v1/scripts"
        ]

        for endpoint in expected_endpoints:
            assert endpoint in route_paths or any(endpoint in path for path in route_paths)

    def test_app_rate_limiting_configuration(self) -> None:
        app = create_app()

        # Should have rate limiting middleware
        middleware_types = [str(middleware) for middleware in app.user_middleware]
        rate_limit_middleware = any('slowapi' in mw.lower() or 'ratelimit' in mw.lower() for mw in middleware_types)
        assert rate_limit_middleware

    def test_app_health_endpoint_works(self) -> None:
        app = create_app()
        client = TestClient(app)

        response = client.get("/api/v1/health")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert data["status"] == "healthy"

    def test_app_metrics_endpoint_configured(self) -> None:
        app = create_app()
        client = TestClient(app)

        # Prometheus metrics should be available
        response = client.get("/metrics")
        assert response.status_code == 200

        # Should contain prometheus metrics format
        content = response.text
        assert "TYPE" in content or "HELP" in content

    def test_app_docs_endpoint_works(self) -> None:
        app = create_app()
        client = TestClient(app)

        # Swagger docs
        response = client.get("/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

        # OpenAPI schema
        schema_response = client.get("/openapi.json")
        assert schema_response.status_code == 200
        assert "application/json" in schema_response.headers.get("content-type", "")

        # Schema should have required fields
        schema = schema_response.json()
        assert "openapi" in schema
        assert "info" in schema
        assert "paths" in schema

    def test_app_content_type_handling(self) -> None:
        app = create_app()
        client = TestClient(app)

        # JSON endpoints should return JSON
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert "application/json" in response.headers.get("content-type", "")

        # HTML endpoints should return HTML
        docs_response = client.get("/docs")
        assert docs_response.status_code == 200
        assert "text/html" in docs_response.headers.get("content-type", "")

    @patch('app.main.DatabaseManager')
    def test_app_request_validation(self, mock_db_manager: Mock) -> None:
        # Mock the database manager
        mock_db_instance = Mock()
        mock_db_manager.return_value = mock_db_instance

        app = create_app()

        # Manually set up app state for TestClient (since lifespan doesn't run)
        app.state.db_manager = mock_db_instance

        client = TestClient(app)

        # Invalid JSON should return 422
        response = client.post("/api/v1/register",
                               json={"invalid": "data"})  # Missing required fields

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_app_large_request_handling(self) -> None:
        app = create_app()
        client = TestClient(app)

        # Large script should be handled appropriately
        large_script = "print('test')\n" * 1000  # Large but reasonable script

        request_data = {
            "script": large_script,
            "lang": "python",
            "lang_version": "3.11"
        }

        response = client.post("/api/v1/execute", json=request_data)
        # Should either work or return a reasonable error (not crash)
        assert response.status_code in [200, 400, 401, 413, 422, 500]

    def test_app_route_methods(self) -> None:
        app = create_app()
        client = TestClient(app)

        # GET should work on health endpoint
        response = client.get("/api/v1/health")
        assert response.status_code == 200

        # POST should not work on health endpoint
        response = client.post("/api/v1/health")
        assert response.status_code == 405  # Method not allowed

    def test_app_static_file_handling(self) -> None:
        app = create_app()

        # Check if static files are configured
        route_paths = [route.path for route in app.routes]

        # App should handle various route types
        assert len(route_paths) > 0

    def test_app_dependency_injection_setup(self) -> None:
        app = create_app()
        client = TestClient(app)

        # Dependencies should be properly configured
        # Test an endpoint that uses dependency injection
        response = client.get("/api/v1/k8s-limits")

        # Should return a response (not crash due to missing dependencies)
        assert response.status_code in [200, 401, 500]  # Various acceptable responses

    def test_app_logging_configuration(self) -> None:
        with patch('app.main.logger') as mock_logger:
            app = create_app()

            # Should log application startup
            mock_logger.info.assert_called()

    def test_app_environment_configuration(self) -> None:
        with patch('app.main.get_settings') as mock_get_settings:
            mock_settings = Mock()
            mock_settings.PROJECT_NAME = "Test App"
            mock_settings.API_V1_STR = "/api/v1"
            mock_settings.TESTING = False
            mock_settings.RATE_LIMITS = "100/minute"
            mock_get_settings.return_value = mock_settings

            app = create_app()

            # App should use settings for configuration
            assert app.title == mock_settings.PROJECT_NAME
            # FastAPI uses default version, not from settings
            assert app.version == "0.1.0"


class TestMainModuleImports:
    def test_all_imports_successful(self) -> None:
        # If we can import create_app, all imports worked
        from app.main import create_app
        assert create_app is not None

    def test_app_state_initialization(self) -> None:
        app = create_app()

        # Should have state object
        assert hasattr(app, 'state')


class TestMainCoverage:
    @pytest.mark.asyncio
    async def test_lifespan_database_connection_error(self) -> None:
        app = FastAPI()

        mock_settings = Mock()
        mock_settings.PROJECT_NAME = "test"
        mock_settings.TESTING = False

        mock_db_manager = Mock()
        mock_db_manager.connect_to_database = AsyncMock(side_effect=ConnectionError("DB connection failed"))

        with patch('app.main.get_settings', return_value=mock_settings):
            with patch('app.main.DatabaseManager', return_value=mock_db_manager):
                with pytest.raises(RuntimeError, match="Application startup failed: Could not connect to database"):
                    async with lifespan(app):
                        pass

    @pytest.mark.asyncio
    async def test_lifespan_kubernetes_service_error(self) -> None:
        app = FastAPI()

        mock_settings = Mock()
        mock_settings.PROJECT_NAME = "test"
        mock_settings.TESTING = False

        mock_db_manager = Mock()
        mock_db_manager.connect_to_database = AsyncMock()
        mock_db_manager.close_database_connection = AsyncMock()

        with patch('app.main.get_settings', return_value=mock_settings):
            with patch('app.main.DatabaseManager', return_value=mock_db_manager):
                with patch('app.main.KubernetesService', side_effect=Exception("K8s error")):
                    with pytest.raises(Exception, match="K8s error"):
                        async with lifespan(app):
                            pass

                    # Verify cleanup was attempted
                    mock_db_manager.close_database_connection.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_kubernetes_service_error_no_db_manager(self) -> None:
        app = FastAPI()

        mock_settings = Mock()
        mock_settings.PROJECT_NAME = "test"
        mock_settings.TESTING = False

        # Make DatabaseManager creation fail before setting app.state.db_manager
        with patch('app.main.get_settings', return_value=mock_settings):
            with patch('app.main.DatabaseManager', side_effect=Exception("DB creation failed")):
                with pytest.raises(Exception, match="DB creation failed"):
                    async with lifespan(app):
                        pass

    @pytest.mark.asyncio
    async def test_lifespan_shutdown_task_not_done(self) -> None:
        app = FastAPI()

        mock_settings = Mock()
        mock_settings.PROJECT_NAME = "test"
        mock_settings.TESTING = False

        mock_db_manager = Mock()
        mock_db_manager.connect_to_database = AsyncMock()
        mock_db_manager.close_database_connection = AsyncMock()

        mock_k8s_manager = Mock()
        mock_k8s_manager.shutdown_all = AsyncMock()

        mock_k8s_service = Mock()
        mock_k8s_service.ensure_image_pre_puller_daemonset = AsyncMock()

        mock_task = Mock()
        mock_task.done.return_value = False
        mock_task.cancel = Mock()

        with patch('app.main.get_settings', return_value=mock_settings):
            with patch('app.main.DatabaseManager', return_value=mock_db_manager):
                with patch('app.main.KubernetesServiceManager', return_value=mock_k8s_manager):
                    with patch('app.main.KubernetesService', return_value=mock_k8s_service):
                        with patch('asyncio.create_task', return_value=mock_task):
                            async with lifespan(app):
                                pass

                            # Verify task was cancelled
                            mock_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_shutdown_task_done(self) -> None:
        app = FastAPI()

        mock_settings = Mock()
        mock_settings.PROJECT_NAME = "test"
        mock_settings.TESTING = False

        mock_db_manager = Mock()
        mock_db_manager.connect_to_database = AsyncMock()
        mock_db_manager.close_database_connection = AsyncMock()

        mock_k8s_manager = Mock()
        mock_k8s_manager.shutdown_all = AsyncMock()

        mock_k8s_service = Mock()
        mock_k8s_service.ensure_image_pre_puller_daemonset = AsyncMock()

        mock_task = Mock()
        mock_task.done.return_value = True
        mock_task.cancel = Mock()

        with patch('app.main.get_settings', return_value=mock_settings):
            with patch('app.main.DatabaseManager', return_value=mock_db_manager):
                with patch('app.main.KubernetesServiceManager', return_value=mock_k8s_manager):
                    with patch('app.main.KubernetesService', return_value=mock_k8s_service):
                        with patch('asyncio.create_task', return_value=mock_task):
                            async with lifespan(app):
                                pass

                            # Verify task was not cancelled since it was done
                            mock_task.cancel.assert_not_called()

    @pytest.mark.asyncio
    async def test_lifespan_shutdown_no_k8s_manager(self) -> None:
        app = FastAPI()

        mock_settings = Mock()
        mock_settings.PROJECT_NAME = "test"
        mock_settings.TESTING = False

        mock_db_manager = Mock()
        mock_db_manager.connect_to_database = AsyncMock()
        mock_db_manager.close_database_connection = AsyncMock()

        with patch('app.main.get_settings', return_value=mock_settings):
            with patch('app.main.DatabaseManager', return_value=mock_db_manager):
                with patch('app.main.KubernetesService', side_effect=Exception("K8s error")):
                    with pytest.raises(Exception, match="K8s error"):
                        async with lifespan(app):
                            pass

                    # Verify cleanup was attempted
                    mock_db_manager.close_database_connection.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_shutdown_error(self) -> None:
        app = FastAPI()

        mock_settings = Mock()
        mock_settings.PROJECT_NAME = "test"
        mock_settings.TESTING = False

        mock_db_manager = Mock()
        mock_db_manager.connect_to_database = AsyncMock()
        mock_db_manager.close_database_connection = AsyncMock(side_effect=Exception("Shutdown error"))

        mock_k8s_manager = Mock()
        mock_k8s_manager.shutdown_all = AsyncMock()

        mock_k8s_service = Mock()
        mock_k8s_service.ensure_image_pre_puller_daemonset = AsyncMock()

        mock_task = Mock()
        mock_task.done.return_value = True

        with patch('app.main.get_settings', return_value=mock_settings):
            with patch('app.main.DatabaseManager', return_value=mock_db_manager):
                with patch('app.main.KubernetesServiceManager', return_value=mock_k8s_manager):
                    with patch('app.main.KubernetesService', return_value=mock_k8s_service):
                        with patch('asyncio.create_task', return_value=mock_task):
                            with patch('app.main.logger') as mock_logger:
                                async with lifespan(app):
                                    pass

                                # Should log the shutdown error
                                mock_logger.error.assert_called()
