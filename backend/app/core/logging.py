import logging
import re
import sys
from typing import TextIO

import structlog
from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource

from app.settings import Settings

SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    # Optional backslashes also catch escaped quotes, as in JSON nested inside JSON (pymongo command logs)
    (
        r"((?:\\?[\"'])?(?:api[_-]?)?(?:key|token|secret|password|passwd|pwd)(?:\\?[\"'])?\s*[:=]\s*(?:\\?[\"'])?)"
        r"((?:[^\"'\\]|\\(?![\"']))+)((?:\\?[\"'])?)",
        r"\1***API_KEY_OR_TOKEN_REDACTED***\3",
    ),
    (r"(Bearer\s+)([A-Za-z0-9\-_]+)", r"\1***BEARER_TOKEN_REDACTED***"),
    (r"(eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+)", r"***JWT_REDACTED***"),
    (r"(mongodb(?:\+srv)?://[^:]+:)([^@]+)(@)", r"\1***MONGODB_REDACTED***\3"),
    (r"(https?://[^:]+:)([^@]+)(@)", r"\1***URL_CREDS_REDACTED***\3"),
]

# Lookbehind starts a match only at the beginning of a run, so sanitizing stays linear on long lines
_EMAIL_PATTERN = re.compile(r"(?<![a-z0-9._%+-])([a-z0-9._%+-]++)@([a-z0-9.-]+\.[a-z]{2,})", re.IGNORECASE)


_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:password|passwd|pwd|secret|token|api[_-]?key|credentials?|authorization|cookie)$", re.IGNORECASE
)
_REDACTED_VALUE = "***REDACTED***"


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
    string value added by prior processors.  Values under a sensitive key
    name (``password``, ``api_key``, ``csrf_token``...) are replaced whole,
    whatever their type.  Emails are masked to show the first 3 characters
    of the local part plus the full domain.
    """
    for key, value in event_dict.items():
        if _SENSITIVE_KEY.search(key) and value is not None:
            event_dict[key] = _REDACTED_VALUE
        elif isinstance(value, str):
            event_dict[key] = _redact(value)
    return event_dict


class RedactedMessage(str):
    """A log message that already went through redaction."""


_render_json = structlog.processors.JSONRenderer()


def render_json(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> RedactedMessage:
    """Render the event as JSON, marked so RedactingFilter passes it through untouched."""
    return RedactedMessage(_render_json(logger, method_name, event_dict))


class RedactingFilter(logging.Filter):
    """Redacts stdlib records from third-party libraries with the rules structlog events get.

    Structlog events arrive already sanitized field by field, so they pass as they are.
    Any other record has its message, traceback and stack rendered to text and redacted
    in place, so every handler after this filter sees only the redacted text.
    """

    _formatter = logging.Formatter()

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, RedactedMessage):
            return True
        message = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = self._formatter.formatException(record.exc_info)
        if record.exc_text:
            message = f"{message}\n{record.exc_text}"
        record.msg = RedactedMessage(_redact(message))
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        if record.stack_info:
            record.stack_info = _redact(record.stack_info)
        return True


class _StderrHandler(logging.StreamHandler[TextIO]):
    """Writes to whatever sys.stderr is at emit time, so a swapped or closed stream never goes stale."""

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stderr
        super().emit(record)


_redacting_filter = RedactingFilter()

_stream_handler = _StderrHandler()
_stream_handler.setFormatter(logging.Formatter("%(message)s"))
_stream_handler.addFilter(_redacting_filter)

# Third-party loggers that are chatty or dump payloads (command documents, API responses, SSE chunks) below WARNING
_QUIET_LOGGERS = (
    "aiohttp",
    "aiokafka",
    "apscheduler",
    "asyncio",
    "grpc",
    "httpcore2",
    "httpx2",
    "kubernetes_asyncio",
    "pymongo",
    "python_multipart",
    "redis",
    "sse_starlette",
    "urllib3",
)


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
            render_json,
        ],
        # --8<-- [end:log_processors]
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    level = logging.getLevelNamesMapping()[log_level.upper()]
    root = logging.getLogger()
    root.addHandler(_stream_handler)
    root.setLevel(level)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(max(level, logging.WARNING))

    logger: structlog.stdlib.BoundLogger = structlog.get_logger("integr8scode")
    return logger


# --8<-- [end:setup_logger]


def setup_log_exporter(settings: Settings, logger: structlog.stdlib.BoundLogger) -> None:
    """Configure OTel LoggerProvider to export logs via OTLP to the collector.

    Adds an OTLP handler to stdlib logging so structlog output flows to both
    stdout (existing StreamHandler) and the OTel Collector (new OTLP handler).
    No-ops when ``settings.OTEL_EXPORTER_OTLP_ENDPOINT`` is empty.

    Args:
        settings: Application settings providing the OTLP endpoint and service metadata.
        logger: Bound logger used to confirm successful configuration.

    Returns:
        None
    """
    if not settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        return

    resource = Resource.create(
        {
            SERVICE_NAME: settings.SERVICE_NAME,
            SERVICE_VERSION: settings.SERVICE_VERSION,
            "service.namespace": "integr8scode",
            "deployment.environment": settings.ENVIRONMENT,
            "service.instance.id": settings.HOSTNAME,
        }
    )

    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
    log_exporter = OTLPLogExporter(
        endpoint=endpoint,
        insecure=endpoint.startswith("http://"),
    )

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    set_logger_provider(logger_provider)

    otel_handler = LoggingHandler(level=logging.DEBUG, logger_provider=logger_provider)
    otel_handler.addFilter(_redacting_filter)
    logging.getLogger().addHandler(otel_handler)

    logger.info("OTLP log export configured", endpoint=endpoint)
