import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import correlation_id_context, logger, request_metadata_context


class CorrelationContext:
    @staticmethod
    def generate_correlation_id() -> str:
        return f"req_{uuid.uuid4()}_{int(datetime.now(timezone.utc).timestamp())}"

    @staticmethod
    def set_correlation_id(correlation_id: str) -> str:
        correlation_id_context.set(correlation_id)
        logger.debug(f"Set correlation ID: {correlation_id}")
        return correlation_id

    @staticmethod
    def get_correlation_id() -> str:
        return correlation_id_context.get() or ""

    @staticmethod
    def set_request_metadata(metadata: Dict[str, Any]) -> None:
        request_metadata_context.set(metadata)
        logger.debug(f"Set request metadata: {metadata}")

    @staticmethod
    def get_request_metadata() -> Dict[str, Any]:
        return request_metadata_context.get() or {}

    @staticmethod
    def clear() -> None:
        correlation_id_context.set(None)
        request_metadata_context.set(None)
        logger.debug("Cleared correlation context")


class CorrelationMiddleware:
    CORRELATION_HEADER = "X-Correlation-ID"
    REQUEST_ID_HEADER = "X-Request-ID"

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Try to get correlation ID from headers
        headers = dict(scope["headers"])
        correlation_id = None

        for header_name in [b"x-correlation-id", b"x-request-id"]:
            if header_name in headers:
                correlation_id = headers[header_name].decode("latin-1")
                break

        # Generate correlation ID if not provided
        if not correlation_id:
            correlation_id = CorrelationContext.generate_correlation_id()

        # Set correlation ID
        correlation_id = CorrelationContext.set_correlation_id(correlation_id)

        # Set request metadata
        client = scope.get("client")
        client_ip = client[0] if client else None

        metadata = {
            "method": scope["method"],
            "path": scope["path"],
            "client": {"host": client_ip} if client_ip else None,
        }
        CorrelationContext.set_request_metadata(metadata)

        # Add correlation ID to response headers
        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers[self.CORRELATION_HEADER] = correlation_id
            await send(message)

        # Process request
        await self.app(scope, receive, send_wrapper)

        # Clear context after request
        CorrelationContext.clear()
