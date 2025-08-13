import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.logging import correlation_id_context, logger, request_metadata_context


class CorrelationContext:
    """Manages correlation IDs and request metadata across async boundaries"""

    @staticmethod
    def generate_correlation_id() -> str:
        """Generate a new correlation ID"""
        return f"req_{uuid.uuid4().hex[:16]}_{int(datetime.now(timezone.utc).timestamp())}"

    @staticmethod
    def set_correlation_id(correlation_id: Optional[str] = None) -> str:
        """
        Set correlation ID in context.
        If no ID provided, generates a new one.
        
        Returns:
            The correlation ID that was set
        """
        if correlation_id is None:
            correlation_id = CorrelationContext.generate_correlation_id()

        correlation_id_context.set(correlation_id)
        logger.debug(f"Set correlation ID: {correlation_id}")
        return correlation_id

    @staticmethod
    def get_correlation_id() -> Optional[str]:
        """Get current correlation ID from context"""
        return correlation_id_context.get()

    @staticmethod
    def set_request_metadata(metadata: Dict[str, Any]) -> None:
        """Set request metadata in context"""
        request_metadata_context.set(metadata)
        logger.debug(f"Set request metadata: {metadata}")

    @staticmethod
    def get_request_metadata() -> Dict[str, Any]:
        """Get current request metadata from context"""
        return request_metadata_context.get() or {}

    @staticmethod
    def clear() -> None:
        """Clear correlation context"""
        correlation_id_context.set(None)
        request_metadata_context.set(None)
        logger.debug("Cleared correlation context")


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Middleware to handle correlation IDs for HTTP requests"""

    CORRELATION_HEADER = "X-Correlation-ID"
    REQUEST_ID_HEADER = "X-Request-ID"

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Try to get correlation ID from headers
        correlation_id = (
                request.headers.get(self.CORRELATION_HEADER) or
                request.headers.get(self.REQUEST_ID_HEADER) or
                request.headers.get("x-correlation-id") or
                request.headers.get("x-request-id")
        )

        # Set correlation ID
        correlation_id = CorrelationContext.set_correlation_id(correlation_id)

        # Set request metadata
        client_host = None
        if request.client:
            client_host = request.client.host

        metadata = {
            "method": request.method,
            "path": request.url.path,
            "client": {
                "host": client_host
            } if client_host else None
        }
        CorrelationContext.set_request_metadata(metadata)

        # Process request
        response = await call_next(request)

        # Add correlation ID to response headers
        response.headers[self.CORRELATION_HEADER] = correlation_id

        # Clear context after request
        CorrelationContext.clear()

        return response
