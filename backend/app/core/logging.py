import contextvars
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

correlation_id_context: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    'correlation_id',
    default=None
)

request_metadata_context: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
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
            if metadata.get("client"):
                record.client_host = metadata["client"].get("host")

        return True


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
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
            log_data['exc_info'] = self.formatException(record.exc_info)

        if hasattr(record, 'stack_info') and record.stack_info:
            log_data['stack_info'] = self.formatStack(record.stack_info)

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
    logger.setLevel(logging.DEBUG)

    return logger


logger = setup_logger()
