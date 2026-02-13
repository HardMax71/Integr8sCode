from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import structlog
from app.core.logging import (
    SENSITIVE_PATTERNS,
    add_otel_context,
    sanitize_sensitive_data,
    setup_logger,
)


class TestSanitizeSensitiveData:
    """Tests for the sanitize_sensitive_data structlog processor."""

    @staticmethod
    def _run_processor(event: str) -> str:
        """Run sanitize_sensitive_data processor and return the sanitized event string."""
        event_dict: dict[str, Any] = {"event": event}
        result = sanitize_sensitive_data(None, "info", event_dict)
        return str(result["event"])

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
            ("user email: test@example.com", "test@example.com", "tes***@example.com"),
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
        result = self._run_processor(input_data)
        assert forbidden_text not in result
        assert expected_marker in result

    def test_sanitizes_multiple_types_in_one_message(self) -> None:
        msg = "Bearer abcd1234 and mongodb://user:secret@host/db and email a@b.com"
        result = self._run_processor(msg)
        assert "BEARER_TOKEN_REDACTED" in result
        assert "MONGODB_REDACTED" in result
        assert "a***@b.com" in result

    def test_non_string_event_unchanged(self) -> None:
        event_dict: dict[str, Any] = {"event": 42}
        result = sanitize_sensitive_data(None, "info", event_dict)
        assert result["event"] == 42

    def test_sanitizes_exc_info_field(self) -> None:
        event_dict: dict[str, Any] = {
            "event": "connection failed",
            "exc_info": "ConnectionError: mongodb://user:secret123@host/db",
        }
        result = sanitize_sensitive_data(None, "error", event_dict)
        assert "secret123" not in result["exc_info"]
        assert "MONGODB_REDACTED" in result["exc_info"]

    def test_sanitizes_stack_info_field(self) -> None:
        event_dict: dict[str, Any] = {
            "event": "debug trace",
            "stack_info": 'password: "hunter2" at line 42',
        }
        result = sanitize_sensitive_data(None, "debug", event_dict)
        assert "hunter2" not in result["stack_info"]

    def test_sanitizes_extra_string_values(self) -> None:
        event_dict: dict[str, Any] = {
            "event": "check",
            "url": "https://admin:s3cret@api.example.com/v1",
            "count": 5,
        }
        result = sanitize_sensitive_data(None, "info", event_dict)
        assert "s3cret" not in result["url"]
        assert "URL_CREDS_REDACTED" in result["url"]
        assert result["count"] == 5

    def test_has_expected_pattern_count(self) -> None:
        assert len(SENSITIVE_PATTERNS) == 5

    @pytest.mark.parametrize(
        ("email", "expected"),
        [
            ("admin@example.com", "adm***@example.com"),
            ("ab@example.com", "ab***@example.com"),
            ("longlocal@domain.org", "lon***@domain.org"),
        ],
        ids=["normal", "short_local", "long_local"],
    )
    def test_email_masked_preserves_prefix_and_domain(self, email: str, expected: str) -> None:
        event_dict: dict[str, Any] = {"event": "action", "detail": email}
        result = sanitize_sensitive_data(None, "info", event_dict)
        assert result["detail"] == expected


class TestAddOtelContext:
    """Tests for the add_otel_context structlog processor."""

    def test_no_span_no_ids(self) -> None:
        event_dict: dict[str, Any] = {"event": "test"}
        result = add_otel_context(None, "info", event_dict)
        assert "trace_id" not in result
        assert "span_id" not in result

    def test_with_valid_span(self) -> None:
        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        mock_ctx = MagicMock()
        mock_ctx.is_valid = True
        mock_ctx.trace_id = 0x1234567890ABCDEF1234567890ABCDEF
        mock_ctx.span_id = 0x1234567890ABCDEF
        mock_span.get_span_context.return_value = mock_ctx

        with patch("app.core.logging.trace.get_current_span", return_value=mock_span):
            event_dict: dict[str, Any] = {"event": "test"}
            result = add_otel_context(None, "info", event_dict)
        assert result["trace_id"] == "1234567890abcdef1234567890abcdef"
        assert result["span_id"] == "1234567890abcdef"


class TestSetupLogger:
    """Tests for logger setup."""

    def test_returns_bound_logger(self) -> None:
        logger = setup_logger("INFO")
        assert hasattr(logger, "info")
        assert hasattr(logger, "bind")
        assert "BoundLogger" in type(logger).__name__ or "LazyProxy" in type(logger).__name__

    def test_has_info_method(self) -> None:
        logger = setup_logger("INFO")
        assert hasattr(logger, "info")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")

    def test_handles_case_insensitive_level(self) -> None:
        logger = setup_logger("debug")
        assert hasattr(logger, "debug")

    def test_logger_captures_event_and_keys(self) -> None:
        structlog.reset_defaults()
        setup_logger("INFO")
        with structlog.testing.capture_logs() as cap_logs:
            structlog.get_logger("integr8scode").info("test message", key="value")
        assert len(cap_logs) >= 1
        assert cap_logs[0]["event"] == "test message"
        assert cap_logs[0]["key"] == "value"
