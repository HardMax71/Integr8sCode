from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class CacheControlMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app
        self.cache_policies: dict[str, str] = {
            "/api/v1/k8s-limits": "public, max-age=300",  # 5 minutes
            "/api/v1/example-scripts": "public, max-age=600",  # 10 minutes
            "/api/v1/auth/verify-token": "private, no-cache",  # 30 seconds
            "/api/v1/notifications": "private, no-cache",  # Always revalidate
            "/api/v1/notifications/unread-count": "private, no-cache",  # Always revalidate
        }

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        path = scope["path"]

        # Only modify headers for GET requests
        if method != "GET":
            await self.app(scope, receive, send)
            return

        cache_control = self._get_cache_policy(path)
        if not cache_control:
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Only add cache headers for successful responses
                status_code = message.get("status", 200)
                if status_code == 200:
                    headers = MutableHeaders(scope=message)
                    headers["Cache-Control"] = cache_control

                    # Add ETag support for better caching
                    if "public" in cache_control:
                        headers["Vary"] = "Accept-Encoding"

            await send(message)

        await self.app(scope, receive, send_wrapper)

    def _get_cache_policy(self, path: str) -> str | None:
        # Exact match first
        if path in self.cache_policies:
            return self.cache_policies[path]

        # Check if path starts with any cache policy key
        for policy_path, cache_control in self.cache_policies.items():
            if path.startswith(policy_path):
                return cache_control

        return None
