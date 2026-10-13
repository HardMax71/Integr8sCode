from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
}


class SecurityHeadersMiddleware:
    """Add standard security response headers to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        await self.app(scope, receive, _SecurityHeadersSend(send))


class _SecurityHeadersSend:
    """One response's ASGI send, adding the security headers when the response starts."""

    def __init__(self, send: Send) -> None:
        self.send = send

    async def __call__(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            MutableHeaders(scope=message).update(_SECURITY_HEADERS)
        await self.send(message)
