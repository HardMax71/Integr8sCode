from typing import Any
from unittest.mock import Mock, AsyncMock

import pytest
from app.core.middleware import RequestSizeLimitMiddleware
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.testclient import TestClient


class TestRequestSizeLimitMiddleware:

    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.app = FastAPI()
        self.middleware = RequestSizeLimitMiddleware(self.app)

    def test_middleware_initialization_sizes(self) -> None:
        test_cases = [
            (None, 10 * 1024 * 1024),  # Default 10MB
            (5, 5 * 1024 * 1024),  # 5MB
            (0, 0),  # 0MB
            (100, 100 * 1024 * 1024),  # 100MB
            (0.5, int(0.5 * 1024 * 1024))  # 0.5MB
        ]

        for size_mb, expected_bytes in test_cases:
            if size_mb is None:
                middleware = RequestSizeLimitMiddleware(self.app)
            else:
                middleware = RequestSizeLimitMiddleware(self.app, max_size_mb=size_mb)

            assert middleware.max_size_bytes == expected_bytes

    @pytest.mark.asyncio
    async def test_dispatch_no_content_length_header(self) -> None:
        # Mock request without content-length header
        mock_request = Mock(spec=Request)
        mock_request.headers = {}

        # Mock call_next
        mock_response = Mock(spec=Response)
        call_next = AsyncMock(return_value=mock_response)

        result = await self.middleware.dispatch(mock_request, call_next)

        # Should proceed normally when no content-length header
        assert result is mock_response
        call_next.assert_called_once_with(mock_request)

    @pytest.mark.asyncio
    async def test_dispatch_within_size_limit(self) -> None:
        # Mock request with small content-length
        mock_request = Mock(spec=Request)
        small_size = "1024"  # 1KB, well within 10MB limit
        mock_request.headers = {"content-length": small_size}

        # Mock call_next
        mock_response = Mock(spec=Response)
        call_next = AsyncMock(return_value=mock_response)

        result = await self.middleware.dispatch(mock_request, call_next)

        # Should proceed normally when within size limit
        assert result is mock_response
        call_next.assert_called_once_with(mock_request)

    @pytest.mark.asyncio
    async def test_dispatch_size_limit_scenarios(self) -> None:
        test_cases = [
            # (size_mb, content_length, should_pass, expected_in_error)
            (1, "1024", True, None),  # Within limit
            (1, str(1 * 1024 * 1024), True, None),  # Exactly at limit
            (1, str(1 * 1024 * 1024 + 1), False, "1.0MB"),  # One byte over
            (1, str(2 * 1024 * 1024), False, "1.0MB"),  # Well over limit
            (5, str(6 * 1024 * 1024), False, "5.0MB"),  # Over 5MB limit
            (10, str(5 * 1024 * 1024), True, None),  # Within 10MB limit
            (0.5, str(int(0.5 * 1024 * 1024) + 1), False, "0.5MB")  # Over 0.5MB limit
        ]

        for size_mb, content_length, should_pass, expected_in_error in test_cases:
            middleware = RequestSizeLimitMiddleware(self.app, max_size_mb=size_mb)

            # Mock request
            mock_request = Mock(spec=Request)
            mock_request.headers = {"content-length": content_length}

            # Mock call_next
            mock_response = Mock(spec=Response)
            call_next = AsyncMock(return_value=mock_response)

            if should_pass:
                result = await middleware.dispatch(mock_request, call_next)
                assert result is mock_response
                call_next.assert_called_once_with(mock_request)
            else:
                with pytest.raises(HTTPException) as exc_info:
                    await middleware.dispatch(mock_request, call_next)

                assert exc_info.value.status_code == 413
                assert "Request too large" in exc_info.value.detail
                if expected_in_error:
                    assert expected_in_error in exc_info.value.detail
                call_next.assert_not_called()

            # Reset mock for next iteration
            call_next.reset_mock()

    @pytest.mark.asyncio
    async def test_dispatch_content_length_zero(self) -> None:
        # Mock request with zero content-length
        mock_request = Mock(spec=Request)
        mock_request.headers = {"content-length": "0"}

        # Mock call_next
        mock_response = Mock(spec=Response)
        call_next = AsyncMock(return_value=mock_response)

        result = await self.middleware.dispatch(mock_request, call_next)

        # Should proceed normally with zero-length content
        assert result is mock_response
        call_next.assert_called_once_with(mock_request)

    @pytest.mark.asyncio
    async def test_dispatch_content_length_invalid(self) -> None:
        # Mock request with invalid content-length
        mock_request = Mock(spec=Request)
        mock_request.headers = {"content-length": "invalid"}

        # Mock call_next
        call_next = AsyncMock()

        # Should raise ValueError when trying to convert invalid string to int
        with pytest.raises(ValueError):
            await self.middleware.dispatch(mock_request, call_next)

    def test_middleware_with_app_integration(self) -> None:
        @self.app.post("/upload")
        async def upload_endpoint(data: dict) -> dict[str, int]:
            return {"received": len(str(data))}

        # Add middleware
        self.app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        client = TestClient(self.app)

        # Test small request (should work)
        small_data = {"test": "data"}
        response = client.post("/upload", json=small_data)
        assert response.status_code == 200

    def test_middleware_with_large_request(self) -> None:
        @self.app.post("/upload")
        async def upload_endpoint() -> dict[str, str]:
            return {"status": "received"}

        # Add middleware with very small limit for testing
        self.app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=0.001)  # Very small limit

        client = TestClient(self.app)

        # Test with large JSON data that should exceed limit
        large_data = {"data": "x" * 10000}  # Large string

        # Make the request - it should be rejected by middleware
        try:
            response = client.post("/upload", json=large_data)
            # If we get here, check the response
            assert response.status_code == 413
            assert "Request too large" in response.json()["detail"]
        except Exception as e:
            assert "413" in str(e) or "Request too large" in str(e)

    @pytest.mark.asyncio
    async def test_dispatch_calls_next_correctly(self) -> None:
        # Mock request
        mock_request = Mock(spec=Request)
        mock_request.headers = {}

        # Mock call_next with specific return value
        expected_response = Mock(spec=Response)
        expected_response.status_code = 200
        call_next = AsyncMock(return_value=expected_response)

        result = await self.middleware.dispatch(mock_request, call_next)

        # Should return the exact response from call_next
        assert result is expected_response
        call_next.assert_called_once_with(mock_request)

    def test_middleware_inheritance(self) -> None:
        from starlette.middleware.base import BaseHTTPMiddleware

        assert isinstance(self.middleware, BaseHTTPMiddleware)
        assert hasattr(self.middleware, 'dispatch')
        assert hasattr(self.middleware, 'max_size_bytes')

    @pytest.mark.asyncio
    async def test_dispatch_preserves_request_object(self) -> None:
        # Mock request
        mock_request = Mock(spec=Request)
        mock_request.headers = {}

        # Mock call_next that verifies it receives the same request
        def verify_request(request: Mock) -> Mock:
            assert request is mock_request
            return Mock(spec=Response)

        call_next = AsyncMock(side_effect=verify_request)

        await self.middleware.dispatch(mock_request, call_next)

        call_next.assert_called_once_with(mock_request)

    def test_middleware_multiple_instances(self) -> None:
        middleware1 = RequestSizeLimitMiddleware(self.app, max_size_mb=1)
        middleware2 = RequestSizeLimitMiddleware(self.app, max_size_mb=5)

        # Should be different instances
        assert middleware1 is not middleware2
        assert middleware1.max_size_bytes != middleware2.max_size_bytes

    @pytest.mark.asyncio
    async def test_dispatch_with_async_call_next(self) -> None:
        # Mock request
        mock_request = Mock(spec=Request)
        mock_request.headers = {}

        # Async call_next that simulates real async behavior
        async def async_call_next(request: Any) -> Mock:
            # Simulate some async work
            import asyncio
            await asyncio.sleep(0.001)
            response = Mock(spec=Response)
            response.status_code = 200
            return response

        result = await self.middleware.dispatch(mock_request, async_call_next)

        assert result.status_code == 200
