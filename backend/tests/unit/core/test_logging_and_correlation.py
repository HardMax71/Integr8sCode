import io
import json
import logging
from typing import Any

import pytest
from app.core.correlation import CorrelationContext, CorrelationMiddleware
from app.core.logging import (
    CorrelationFilter,
    JSONFormatter,
    correlation_id_context,
    request_metadata_context,
    setup_logger,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def capture_log(
    formatter: logging.Formatter,
    msg: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Capture log output as parsed JSON."""
    logger = logging.getLogger("test_capture")

    string_io = io.StringIO()
    stream = logging.StreamHandler(string_io)
    stream.setFormatter(formatter)

    correlation_filter = CorrelationFilter()
    stream.addFilter(correlation_filter)

    logger.handlers = [stream]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    logger.info(msg, extra=extra or {})
    stream.flush()

    output = string_io.getvalue()
    string_io.close()

    if output:
        result: dict[str, Any] = json.loads(output)
        return result

    # Fallback: create and format record manually
    lr = logging.LogRecord("test", logging.INFO, __file__, 1, msg, (), None, None)
    correlation_filter.filter(lr)
    s = formatter.format(lr)
    fallback_result: dict[str, Any] = json.loads(s)
    return fallback_result


class TestJSONFormatter:
    """Tests for JSON log formatter."""

    def test_formats_as_valid_json(self) -> None:
        """Formatter outputs valid JSON."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["message"] == "Test message"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test"
        assert "timestamp" in parsed

    def test_includes_correlation_id_from_record(self) -> None:
        """Formatter includes correlation_id when present on record."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None,
        )
        record.correlation_id = "req_12345"

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["correlation_id"] == "req_12345"

    def test_includes_request_metadata_from_record(self) -> None:
        """Formatter includes request metadata when present on record."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None,
        )
        record.request_method = "POST"
        record.request_path = "/api/v1/execute"
        record.client_host = "192.168.1.1"

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["request_method"] == "POST"
        assert parsed["request_path"] == "/api/v1/execute"
        assert parsed["client_host"] == "192.168.1.1"


class TestSensitiveDataSanitization:
    """Tests for sensitive data sanitization in logs."""

    @pytest.mark.parametrize(
        ("input_data", "forbidden_text", "expected_marker"),
        [
            ("api_key: secret12345", "secret12345", "REDACTED"),
            ("Authorization: Bearer abc123xyz", "abc123xyz", "BEARER_TOKEN_REDACTED"),
            (
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
                "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
                "JWT_REDACTED",
            ),
            (
                "mongodb://myuser:secretpass@localhost:27017/mydb",
                "secretpass",
                "MONGODB_REDACTED",
            ),
            ("user email: test@example.com", "test@example.com", "EMAIL_REDACTED"),
            ('password: "mysecret123"', "mysecret123", "REDACTED"),
            (
                "https://user:password@api.example.com/endpoint",
                "password",
                "URL_CREDS_REDACTED",
            ),
        ],
        ids=[
            "api_key",
            "bearer_token",
            "jwt_token",
            "mongodb_url",
            "email",
            "password_field",
            "https_credentials",
        ],
    )
    def test_sanitizes_sensitive_data(
        self, input_data: str, forbidden_text: str, expected_marker: str
    ) -> None:
        """Sensitive data is redacted from logs."""
        formatter = JSONFormatter()

        result = formatter._sanitize_sensitive_data(input_data)

        assert forbidden_text not in result
        assert expected_marker in result

    def test_sanitizes_multiple_types_in_one_message(self) -> None:
        """Multiple sensitive data types are sanitized in a single message."""
        formatter = JSONFormatter()
        msg = "Bearer abcd1234 and mongodb://user:secret@host/db and email a@b.com"

        result = capture_log(formatter, msg)
        sanitized = result["message"]

        assert "BEARER_TOKEN_REDACTED" in sanitized
        assert "MONGODB_REDACTED" in sanitized
        assert "EMAIL_REDACTED" in sanitized


class TestCorrelationFilter:
    """Tests for correlation filter."""

    def test_adds_correlation_id_from_context(self) -> None:
        """Filter adds correlation_id from context to record."""
        filter_ = CorrelationFilter()

        token = correlation_id_context.set("test-correlation-123")
        try:
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg="Test",
                args=(),
                exc_info=None,
            )

            result = filter_.filter(record)

            assert result is True
            assert record.correlation_id == "test-correlation-123"  # type: ignore[attr-defined]
        finally:
            correlation_id_context.reset(token)

    def test_adds_request_metadata_from_context(self) -> None:
        """Filter adds request metadata from context to record."""
        filter_ = CorrelationFilter()

        metadata = {
            "method": "GET",
            "path": "/api/v1/test",
            "client": {"host": "127.0.0.1"},
        }
        token = request_metadata_context.set(metadata)
        try:
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg="Test",
                args=(),
                exc_info=None,
            )

            result = filter_.filter(record)

            assert result is True
            assert record.request_method == "GET"  # type: ignore[attr-defined]
            assert record.request_path == "/api/v1/test"  # type: ignore[attr-defined]
            assert record.client_host == "127.0.0.1"  # type: ignore[attr-defined]
        finally:
            request_metadata_context.reset(token)

    def test_always_returns_true(self) -> None:
        """Filter always returns True (never drops records)."""
        filter_ = CorrelationFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None,
        )

        assert filter_.filter(record) is True


class TestCorrelationContext:
    """Tests for CorrelationContext usage."""

    def test_context_and_filter_integration(self) -> None:
        """CorrelationContext integrates with CorrelationFilter."""
        CorrelationContext.set_correlation_id("cid-1")
        CorrelationContext.set_request_metadata(
            {"method": "GET", "path": "/x", "client": {"host": "1.2.3.4"}}
        )

        result = capture_log(JSONFormatter(), "hello")

        assert result["correlation_id"] == "cid-1"
        assert result["request_method"] == "GET"
        assert result["request_path"] == "/x"
        assert result["client_host"] == "1.2.3.4"

        CorrelationContext.clear()


class TestCorrelationMiddleware:
    """Tests for CorrelationMiddleware."""

    def test_sets_correlation_header(self) -> None:
        """Middleware sets X-Correlation-ID response header."""

        async def ping(request: Request) -> JSONResponse:
            return JSONResponse({"ok": True})

        app = Starlette(routes=[Route("/ping", ping)])
        app.add_middleware(CorrelationMiddleware)

        with TestClient(app) as client:
            response = client.get("/ping")

            assert response.status_code == 200
            assert "X-Correlation-ID" in response.headers


class TestSetupLogger:
    """Tests for logger setup."""

    def test_creates_named_logger(self) -> None:
        """setup_logger creates logger with correct name."""
        logger = setup_logger("INFO")

        assert logger.name == "integr8scode"

    def test_sets_correct_level(self) -> None:
        """Logger is set to correct level."""
        logger = setup_logger("WARNING")

        assert logger.level == logging.WARNING

    def test_handles_case_insensitive_level(self) -> None:
        """Logger handles case-insensitive level strings."""
        logger = setup_logger("debug")

        assert logger.level == logging.DEBUG

    def test_has_json_formatter(self) -> None:
        """Logger has JSON formatter attached."""
        logger = setup_logger("INFO")

        assert len(logger.handlers) > 0
        handler = logger.handlers[0]
        assert isinstance(handler.formatter, JSONFormatter)

    def test_has_correlation_filter(self) -> None:
        """Logger has correlation filter attached."""
        logger = setup_logger("INFO")

        assert len(logger.handlers) > 0
        handler = logger.handlers[0]
        filter_types = [type(f).__name__ for f in handler.filters]
        assert "CorrelationFilter" in filter_types

    def test_clears_existing_handlers(self) -> None:
        """setup_logger clears existing handlers."""
        logger1 = setup_logger("INFO")
        initial_handlers = len(logger1.handlers)

        logger2 = setup_logger("DEBUG")

        assert len(logger2.handlers) == initial_handlers

    def test_returns_logger(self) -> None:
        """setup_logger returns a logger instance."""
        lg = setup_logger(log_level="INFO")

        assert hasattr(lg, "info")
