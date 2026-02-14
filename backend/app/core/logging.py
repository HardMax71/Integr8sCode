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
]

_EMAIL_PATTERN = re.compile(r"([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", re.IGNORECASE)


def _mask_email(match: re.Match[str]) -> str:
    local = match.group(1)
    domain = match.group(2)
    return f"{local[:3]}***@{domain}"


def _redact(value: str) -> str:
    for pattern, replacement in SENSITIVE_PATTERNS:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    value = _EMAIL_PATTERN.sub(_mask_email, value)
    return value


def sanitize_sensitive_data(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Structlog processor that redacts sensitive data from all string fields.

    Covers event message, formatted exception text, stack info, and any
    string value added by prior processors.  Emails are masked to show the
    first 3 characters of the local part plus the full domain.
    """
    for key, value in event_dict.items():
        if isinstance(value, str):
            event_dict[key] = _redact(value)
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


# --8<-- [start:setup_logger]
def setup_logger(log_level: str) -> structlog.stdlib.BoundLogger:
    """Configure structlog and return a bound logger for the application.

    Called by DI with Settings.LOG_LEVEL and also directly by main.py/lifespan.
    """
    structlog.configure(
        # --8<-- [start:log_processors]
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            add_otel_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            sanitize_sensitive_data,
            structlog.processors.JSONRenderer(),
        ],
        # --8<-- [end:log_processors]
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(format="%(message)s", handlers=[logging.StreamHandler()])
    logging.getLogger().setLevel(log_level.upper())

    logger: structlog.stdlib.BoundLogger = structlog.get_logger("integr8scode")
    return logger
# --8<-- [end:setup_logger]
