import contextvars
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict

from app.settings import get_settings

correlation_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    'correlation_id',
    default=None
)

request_metadata_context: contextvars.ContextVar[Dict[str, Any] | None] = contextvars.ContextVar(
    'request_metadata',
    default=None
)


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        correlation_id = correlation_id_context.get()
        if correlation_id:
            record.correlation_id = correlation_id

        metadata = request_metadata_context.get()
        if metadata:
            record.request_method = metadata.get("method")
            record.request_path = metadata.get("path")
            # Client IP is now safely extracted without DNS lookup
            if metadata.get("client"):
                record.client_host = metadata["client"].get("host")

        return True


class JSONFormatter(logging.Formatter):
    def _sanitize_sensitive_data(self, data: str) -> str:
        """Remove or mask sensitive information from log data."""
        # Mask API keys, tokens, and similar sensitive data
        patterns = [
            # API keys and tokens
            (r'(["\']?(?:api[_-]?)?(?:key|token|secret|password|passwd|pwd)["\']?\s*[:=]\s*["\']?)([^"\']+)(["\']?)',
             r'\1***API_KEY_OR_TOKEN_REDACTED***\3'),
            # Bearer tokens
            (r'(Bearer\s+)([A-Za-z0-9\-_]+)', r'\1***BEARER_TOKEN_REDACTED***'),
            # JWT tokens
            (r'(eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+)', r'***JWT_REDACTED***'),
            # MongoDB URLs with credentials
            (r'(mongodb(?:\+srv)?://[^:]+:)([^@]+)(@)', r'\1***MONGODB_REDACTED***\3'),
            # Generic URLs with credentials
            (r'(https?://[^:]+:)([^@]+)(@)', r'\1***URL_CREDS_REDACTED***\3'),
            # Email addresses (optional - uncomment if needed)
            (r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', r'***EMAIL_REDACTED***'),
        ]

        for pattern, replacement in patterns:
            data = re.sub(pattern, replacement, data, flags=re.IGNORECASE)

        return data

    def format(self, record: logging.LogRecord) -> str:
        # Sanitize the message
        message = self._sanitize_sensitive_data(record.getMessage())

        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }

        if hasattr(record, 'correlation_id'):
            log_data['correlation_id'] = record.correlation_id

        if hasattr(record, 'request_method'):
            log_data['request_method'] = record.request_method

        if hasattr(record, 'request_path'):
            log_data['request_path'] = record.request_path

        if hasattr(record, 'client_host'):
            log_data['client_host'] = record.client_host

        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            log_data['exc_info'] = self._sanitize_sensitive_data(exc_text)

        if hasattr(record, 'stack_info') and record.stack_info:
            stack_text = self.formatStack(record.stack_info)
            log_data['stack_info'] = self._sanitize_sensitive_data(stack_text)

        return json.dumps(log_data, ensure_ascii=False)


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("integr8scode")
    logger.handlers.clear()

    console_handler = logging.StreamHandler()
    formatter = JSONFormatter()

    console_handler.setFormatter(formatter)

    correlation_filter = CorrelationFilter()
    console_handler.addFilter(correlation_filter)

    logger.addHandler(console_handler)

    # Get log level from configuration
    settings = get_settings()
    log_level_name = settings.LOG_LEVEL.upper()
    log_level = getattr(logging, log_level_name, logging.DEBUG)
    logger.setLevel(log_level)

    return logger


logger = setup_logger()
