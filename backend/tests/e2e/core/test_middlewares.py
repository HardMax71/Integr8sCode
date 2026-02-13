import httpx
import pytest
from app.settings import Settings

pytestmark = pytest.mark.e2e


class TestCSRFMiddleware:
    """Tests for CSRFMiddleware."""

    @pytest.mark.asyncio
    async def test_get_requests_skip_csrf(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET requests skip CSRF validation."""
        response = await client.get("/api/v1/health/live")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_auth_endpoints_skip_csrf(
        self, client: httpx.AsyncClient
    ) -> None:
        """Auth endpoints skip CSRF validation."""
        # Login endpoint should work without CSRF token
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": "nonexistent", "password": "wrong"},
        )

        # 401 means auth failed but CSRF didn't block it
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_authenticated_post_requires_csrf(
        self, test_user: httpx.AsyncClient
    ) -> None:
        """Authenticated POST requires CSRF token."""
        # Remove CSRF header temporarily
        csrf_token = test_user.headers.get("X-CSRF-Token")
        del test_user.headers["X-CSRF-Token"]

        response = await test_user.post(
            "/api/v1/execute",
            json={"script": "print('test')", "lang": "python"},
        )

        # Restore header
        test_user.headers["X-CSRF-Token"] = csrf_token

        # Should be rejected for missing CSRF
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_authenticated_post_with_csrf_succeeds(
        self, test_user: httpx.AsyncClient
    ) -> None:
        """Authenticated POST with valid CSRF token succeeds."""
        response = await test_user.post(
            "/api/v1/execute",
            json={
                "script": "print('hello')",
                "lang": "python",
                "lang_version": "3.11",
            },
        )

        # Should succeed (or at least not be blocked by CSRF)
        assert response.status_code != 403


class TestRequestSizeLimit:
    """Tests for check_request_size dependency."""

    @pytest.mark.asyncio
    async def test_small_request_allowed(
        self, client: httpx.AsyncClient
    ) -> None:
        """Small requests are allowed through."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "testuser",
                "email": "test@example.com",
                "password": "TestPass123!",
            },
        )

        # Not 413 (request too large)
        assert response.status_code != 413

    @pytest.mark.asyncio
    async def test_large_request_rejected(
        self, client: httpx.AsyncClient
    ) -> None:
        """Requests exceeding size limit are rejected."""
        # Create a payload larger than 10MB
        large_payload = "x" * (11 * 1024 * 1024)  # 11MB

        response = await client.post(
            "/api/v1/auth/register",
            content=large_payload,
            headers={"Content-Type": "text/plain"},
        )

        assert response.status_code == 413
        assert "too large" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_large_request_without_content_length_rejected(
        self, client: httpx.AsyncClient
    ) -> None:
        """Requests without Content-Length header are still checked by body size."""
        large_payload = "x" * (11 * 1024 * 1024)  # 11MB

        response = await client.post(
            "/api/v1/auth/register",
            content=large_payload,
            headers={"Content-Type": "text/plain", "Transfer-Encoding": "chunked"},
        )

        assert response.status_code == 413


class TestCacheControlMiddleware:
    """Tests for CacheControlMiddleware."""

    @pytest.mark.asyncio
    async def test_k8s_limits_cached(self, client: httpx.AsyncClient) -> None:
        """K8s limits endpoint has cache headers."""
        response = await client.get("/api/v1/k8s-limits")

        assert response.status_code == 200
        cache_control = response.headers.get("Cache-Control", "")
        assert "public" in cache_control
        assert "max-age=300" in cache_control

    @pytest.mark.asyncio
    async def test_example_scripts_cached(
        self, client: httpx.AsyncClient
    ) -> None:
        """Example scripts endpoint has cache headers."""
        response = await client.get("/api/v1/example-scripts")

        assert response.status_code == 200
        cache_control = response.headers.get("Cache-Control", "")
        assert "public" in cache_control
        assert "max-age=600" in cache_control

    @pytest.mark.asyncio
    async def test_notifications_no_cache(
        self, test_user: httpx.AsyncClient
    ) -> None:
        """Notifications endpoint has no-cache headers."""
        response = await test_user.get("/api/v1/notifications")

        assert response.status_code == 200
        cache_control = response.headers.get("Cache-Control", "")
        assert "no-cache" in cache_control

    @pytest.mark.asyncio
    async def test_post_no_cache_headers(
        self, test_user: httpx.AsyncClient
    ) -> None:
        """POST requests don't get cache headers."""
        response = await test_user.post(
            "/api/v1/execute",
            json={
                "script": "print('test')",
                "lang": "python",
                "lang_version": "3.11",
            },
        )

        # POST should not have cache-control set by CacheControlMiddleware
        cache_control = response.headers.get("Cache-Control", "")
        # If cache-control is set, it shouldn't be the public caching type
        if cache_control:
            assert "public" not in cache_control or "max-age=300" not in cache_control


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware."""

    @pytest.mark.asyncio
    async def test_rate_limit_headers_present(
        self, client: httpx.AsyncClient, test_settings: Settings
    ) -> None:
        """Rate limit headers are added to responses when rate limiting is enabled."""
        if not test_settings.RATE_LIMIT_ENABLED:
            pytest.skip("Rate limiting is disabled in test config")

        response = await client.get("/api/v1/k8s-limits")

        assert response.status_code == 200
        # Rate limit headers should be present
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers

    @pytest.mark.asyncio
    async def test_health_endpoint_exempt(
        self, client: httpx.AsyncClient
    ) -> None:
        """Health endpoints are exempt from rate limiting."""
        # Make many requests to health endpoint
        for _ in range(20):
            response = await client.get("/api/v1/health/live")
            # Should never get rate limited
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_auth_endpoints_exempt(
        self, client: httpx.AsyncClient
    ) -> None:
        """Auth endpoints are exempt from rate limiting."""
        # Make many login attempts
        for _ in range(10):
            response = await client.post(
                "/api/v1/auth/login",
                data={"username": "test", "password": "wrong"},
            )
            # Should never be 429 (rate limited) — auth endpoints are exempt
            assert response.status_code != 429


class TestMiddlewareOrder:
    """Tests for middleware execution order."""

    @pytest.mark.asyncio
    async def test_all_middlewares_work_together(
        self, test_user: httpx.AsyncClient, test_settings: Settings
    ) -> None:
        """All middlewares work correctly in combination."""
        response = await test_user.get("/api/v1/notifications")

        # Cache control middleware ran
        assert "Cache-Control" in response.headers

        # Rate limit middleware ran (only if enabled)
        if test_settings.RATE_LIMIT_ENABLED:
            assert "X-RateLimit-Limit" in response.headers

        # Request completed successfully
        assert response.status_code == 200
