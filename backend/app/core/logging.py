import contextvars
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace

correlation_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)

request_metadata_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "request_metadata", default=None
)


class JSONFormatter(logging.Formatter):
    """JSON formatter that reads context directly from typed sources."""

    def _sanitize_sensitive_data(self, data: str) -> str:
        """Remove or mask sensitive information from log data."""
        # Mask API keys, tokens, and similar sensitive data
        patterns = [
            # API keys and tokens
            (
                r'(["\']?(?:api[_-]?)?(?:key|token|secret|password|passwd|pwd)["\']?\s*[:=]\s*["\']?)([^"\']+)(["\']?)',
                r"\1***API_KEY_OR_TOKEN_REDACTED***\3",
            ),
            # Bearer tokens
            (r"(Bearer\s+)([A-Za-z0-9\-_]+)", r"\1***BEARER_TOKEN_REDACTED***"),
            # JWT tokens
            (r"(eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+)", r"***JWT_REDACTED***"),
            # MongoDB URLs with credentials
            (r"(mongodb(?:\+srv)?://[^:]+:)([^@]+)(@)", r"\1***MONGODB_REDACTED***\3"),
            # Generic URLs with credentials
            (r"(https?://[^:]+:)([^@]+)(@)", r"\1***URL_CREDS_REDACTED***\3"),
            # Email addresses (optional - uncomment if needed)
            (r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", r"***EMAIL_REDACTED***"),
        ]

        for pattern, replacement in patterns:
            data = re.sub(pattern, replacement, data, flags=re.IGNORECASE)

        return data

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self._sanitize_sensitive_data(record.getMessage()),
        }

        # Correlation context - read directly from typed ContextVar
        (v := correlation_id_context.get()) and log_data.update(correlation_id=v)

        # Request metadata - read directly from typed ContextVar
        metadata = request_metadata_context.get() or {}
        (v := metadata.get("method")) and log_data.update(request_method=v)
        (v := metadata.get("path")) and log_data.update(request_path=v)
        (v := (metadata.get("client") or {}).get("host")) and log_data.update(client_host=v)

        # OpenTelemetry trace context - read directly from typed trace API
        span = trace.get_current_span()
        if span.is_recording():
            span_context = span.get_span_context()
            if span_context.is_valid:
                log_data["trace_id"] = format(span_context.trace_id, "032x")
                log_data["span_id"] = format(span_context.span_id, "016x")

        record.exc_info and log_data.update(
            exc_info=self._sanitize_sensitive_data(self.formatException(record.exc_info))
        )
        record.stack_info and log_data.update(
            stack_info=self._sanitize_sensitive_data(self.formatStack(record.stack_info))
        )

        return json.dumps(log_data, ensure_ascii=False)


def setup_logger(log_level: str) -> logging.Logger:
    """Create and configure the application logger. Called by DI with Settings.LOG_LEVEL."""
    new_logger = logging.getLogger("integr8scode")
    new_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(JSONFormatter())
    new_logger.addHandler(console_handler)
    new_logger.setLevel(logging.getLevelNamesMapping().get(log_level.upper(), logging.DEBUG))

    return new_logger
