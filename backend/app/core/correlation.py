import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

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


class CorrelationMiddleware(BaseHTTPMiddleware):
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

        # Generate correlation ID if not provided
        if not correlation_id:
            correlation_id = CorrelationContext.generate_correlation_id()
        
        # Set correlation ID
        correlation_id = CorrelationContext.set_correlation_id(correlation_id)

        # Set request metadata
        client_ip = request.client.host if request.client else None
        
        metadata = {
            "method": request.method,
            "path": request.url.path,
            "client": {
                "host": client_ip
            } if client_ip else None
        }
        CorrelationContext.set_request_metadata(metadata)

        # Process request
        try:
            response = await call_next(request)

            # Add correlation ID to response headers
            response.headers[self.CORRELATION_HEADER] = correlation_id

            return response
        finally:
            # Clear context after request
            CorrelationContext.clear()
