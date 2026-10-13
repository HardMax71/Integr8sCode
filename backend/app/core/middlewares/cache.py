from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class CacheControlMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app
        # --8<-- [start:cache_policies]
        self.cache_policies: dict[str, str] = {
            "/api/v1/k8s-limits": "public, max-age=300",  # 5 minutes
            "/api/v1/example-scripts": "public, max-age=600",  # 10 minutes
            "/api/v1/notifications": "private, no-cache",  # Always revalidate
            "/api/v1/notifications/unread-count": "private, no-cache",  # Always revalidate
        }
        # --8<-- [end:cache_policies]

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

        await self.app(scope, receive, _CacheHeadersSend(send, cache_control))

    def _get_cache_policy(self, path: str) -> str | None:
        # Exact match first
        if path in self.cache_policies:
            return self.cache_policies[path]

        # Check if path starts with any cache policy key
        for policy_path, cache_control in self.cache_policies.items():
            if path.startswith(policy_path):
                return cache_control

        return None


class _CacheHeadersSend:
    """One GET response's ASGI send, adding the path's cache policy when the response is a 200."""

    def __init__(self, send: Send, cache_control: str) -> None:
        self.send = send
        self.cache_control = cache_control

    async def __call__(self, message: Message) -> None:
        if message["type"] == "http.response.start" and message.get("status", 200) == 200:
            headers = MutableHeaders(scope=message)
            headers["Cache-Control"] = self.cache_control
            if "public" in self.cache_control:
                headers["Vary"] = "Accept-Encoding"
        await self.send(message)
