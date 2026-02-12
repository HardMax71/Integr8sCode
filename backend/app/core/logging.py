import logging
import re

import structlog
from opentelemetry import trace

SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    (
        r'(["\']?(?:api[_-]?)?(?:key|token|secret|password|passwd|pwd)["\']?\s*[:=]\s*["\']?)([^"\']+)(["\']?)',
        r"\1***API_KEY_OR_TOKEN_REDACTED***\3",
    ),
    (r"(Bearer\s+)([A-Za-z0-9\-_]+)", r"\1***BEARER_TOKEN_REDACTED***"),
    (r"(eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+)", r"***JWT_REDACTED***"),
    (r"(mongodb(?:\+srv)?://[^:]+:)([^@]+)(@)", r"\1***MONGODB_REDACTED***\3"),
    (r"(https?://[^:]+:)([^@]+)(@)", r"\1***URL_CREDS_REDACTED***\3"),
    (r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", r"***EMAIL_REDACTED***"),
]


def sanitize_sensitive_data(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Structlog processor that redacts sensitive data from the event message."""
    event = event_dict.get("event", "")
    if isinstance(event, str):
        for pattern, replacement in SENSITIVE_PATTERNS:
            event = re.sub(pattern, replacement, event, flags=re.IGNORECASE)
        event_dict["event"] = event
    return event_dict


def add_otel_context(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Structlog processor that adds OpenTelemetry trace/span IDs."""
    span = trace.get_current_span()
    if span and span.is_recording():
        span_context = span.get_span_context()
        if span_context.is_valid:
            event_dict["trace_id"] = format(span_context.trace_id, "032x")
            event_dict["span_id"] = format(span_context.span_id, "016x")
    return event_dict


LOG_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def setup_logger(log_level: str) -> structlog.stdlib.BoundLogger:
    """Configure structlog and return a bound logger for the application.

    Called by DI with Settings.LOG_LEVEL and also directly by main.py/lifespan.
    """
    level = LOG_LEVELS.get(log_level.upper(), logging.DEBUG)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            sanitize_sensitive_data,
            add_otel_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=level, format="%(message)s", handlers=[logging.StreamHandler()])
    logging.getLogger().setLevel(level)

    logger: structlog.stdlib.BoundLogger = structlog.get_logger("integr8scode")
    return logger
