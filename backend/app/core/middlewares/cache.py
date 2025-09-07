from typing import Awaitable, Callable, Dict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class CacheControlMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.cache_policies: Dict[str, str] = {
            "/api/v1/k8s-limits": "public, max-age=300",  # 5 minutes
            "/api/v1/example-scripts": "public, max-age=600",  # 10 minutes
            "/api/v1/auth/verify-token": "private, no-cache",  # 30 seconds
            "/api/v1/notifications": "private, no-cache",  # Always revalidate
            "/api/v1/notifications/unread-count": "private, no-cache",  # Always revalidate
        }

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response: Response = await call_next(request)

        # Only add cache headers for successful GET requests
        if request.method == "GET" and response.status_code == 200:
            path = request.url.path

            # Find matching cache policy
            cache_control = self._get_cache_policy(path)
            if cache_control:
                response.headers["Cache-Control"] = cache_control

                # Add ETag support for better caching
                if "public" in cache_control:
                    response.headers["Vary"] = "Accept-Encoding"

        return response

    def _get_cache_policy(self, path: str) -> str | None:
        # Exact match first
        if path in self.cache_policies:
            return self.cache_policies[path]

        # Check if path starts with any cache policy key
        for policy_path, cache_control in self.cache_policies.items():
            if path.startswith(policy_path):
                return cache_control

        return None
