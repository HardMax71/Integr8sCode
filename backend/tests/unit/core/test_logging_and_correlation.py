import json
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import structlog
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from pydantic import SecretStr
from pymongo.logger import LogMessage

from app.core.logging import (
    add_otel_context,
    sanitize_sensitive_data,
    setup_log_exporter,
    setup_logger,
)
from app.db.docs import UserDocument
from app.domain.enums import UserRole
from app.domain.user import LoginResult
from app.settings import Settings

_EMAIL = "john.doe@example.com"
_PASSWORD = "hunter2-secret"
_BEARER = "abc123xyz"


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
    def test_sanitizes_sensitive_data(self, input_data: str, forbidden_text: str, expected_marker: str) -> None:
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

    @pytest.mark.parametrize(
        "key",
        [
            "password",
            "new_password",
            "hashed_password",
            "api_key",
            "csrf_token",
            "SECRET",
            "Authorization",
            "x-api-key",
        ],
    )
    def test_redacts_values_under_sensitive_keys(self, key: str) -> None:
        event_dict: dict[str, Any] = {"event": "login", key: "hunter2"}
        result = sanitize_sensitive_data(None, "info", event_dict)
        assert result[key] == "***REDACTED***"

    @pytest.mark.parametrize("key", ["key", "idempotency_key", "token_type", "token_expires_in_minutes", "keyword"])
    def test_keeps_values_under_ordinary_keys(self, key: str) -> None:
        event_dict: dict[str, Any] = {"event": "x", key: "plain-value"}
        result = sanitize_sensitive_data(None, "info", event_dict)
        assert result[key] == "plain-value"

    @pytest.mark.parametrize(
        ("email", "expected"),
        [
            ("admin@example.com", "adm***@example.com"),
            ("ab@example.com", "ab***@example.com"),
            ("longlocal@domain.org", "lon***@domain.org"),
            ("u\u017fer@example.com", "u\u017fe***@example.com"),
        ],
        ids=["normal", "short_local", "long_local", "casefolded_non_ascii"],
    )
    def test_email_masked_preserves_prefix_and_domain(self, email: str, expected: str) -> None:
        event_dict: dict[str, Any] = {"event": "action", "detail": email}
        result = sanitize_sensitive_data(None, "info", event_dict)
        assert result["detail"] == expected

    @pytest.mark.timeout(2)
    @pytest.mark.parametrize(
        "line",
        ["x@" + "a." * 20_000 + "1", "a" * 40_000 + "!"],
        ids=["long_domain_run", "long_run_without_at"],
    )
    def test_email_masking_stays_linear_on_long_lines(self, line: str) -> None:
        assert self._run_processor(line) == line


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

    @pytest.mark.parametrize("level", ["debug", "DEBUG"])
    def test_sets_the_root_level_from_any_case(self, level: str) -> None:
        setup_logger(level)
        assert logging.getLogger().level == logging.DEBUG

    def test_keeps_library_loggers_at_warning_or_above(self) -> None:
        setup_logger("DEBUG")
        assert logging.getLogger("aiokafka").level == logging.WARNING

    def test_logger_captures_event_and_keys(self) -> None:
        setup_logger("INFO")
        with structlog.testing.capture_logs() as cap_logs:
            structlog.get_logger("integr8scode").info("test message", key="value")
        assert len(cap_logs) >= 1
        assert cap_logs[0]["event"] == "test message"
        assert cap_logs[0]["key"] == "value"


_SENSITIVE_RECORDS = [
    pytest.param(
        "some.library",
        "user %s sent Bearer %s, password: %s",
        (_EMAIL, _BEARER, _PASSWORD),
        id="plain_record",
    ),
    pytest.param(
        "pymongo.command",
        LogMessage(
            message="Command failed",
            commandName="insert",
            command={
                "insert": "users",
                "documents": [{"email": _EMAIL, "hashed_password": _PASSWORD, "auth": f"Bearer {_BEARER}"}],
            },
        ),
        (),
        id="pymongo_record",
    ),
]


def _assert_redacted(text: str) -> None:
    assert _EMAIL not in text
    assert _PASSWORD not in text
    assert _BEARER not in text
    assert "joh***@example.com" in text
    assert "API_KEY_OR_TOKEN_REDACTED" in text
    assert "BEARER_TOKEN_REDACTED" in text


class TestStdlibRecordRedaction:
    """Records from third-party stdlib loggers get the same redaction as structlog events."""

    @pytest.mark.parametrize(("name", "msg", "args"), _SENSITIVE_RECORDS)
    def test_stream_handler_redacts(
        self,
        name: str,
        msg: object,
        args: tuple[object, ...],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        setup_logger("DEBUG")
        logging.getLogger(name).warning(msg, *args)

        lines = capsys.readouterr().err.splitlines()
        assert len(lines) == 1
        _assert_redacted(lines[0])

    @pytest.mark.parametrize(("name", "msg", "args"), _SENSITIVE_RECORDS)
    def test_otel_handler_redacts(
        self,
        name: str,
        msg: object,
        args: tuple[object, ...],
        test_settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
        settings = test_settings.model_copy(update={"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317"})
        exporter = InMemoryLogRecordExporter()  # type: ignore[no-untyped-call]
        root = logging.getLogger()
        monkeypatch.setattr(root, "handlers", list(root.handlers))
        before = list(root.handlers)
        with (
            patch("app.core.logging.OTLPLogExporter", return_value=exporter),
            patch("app.core.logging.BatchLogRecordProcessor", SimpleLogRecordProcessor),
            patch("app.core.logging.set_logger_provider"),
        ):
            setup_log_exporter(settings, MagicMock())
        (otel_handler,) = [h for h in root.handlers if h not in before and isinstance(h, LoggingHandler)]

        otel_handler.handle(logging.getLogger(name).makeRecord(name, logging.WARNING, __file__, 0, msg, args, None))

        bodies = [str(log.log_record.body) for log in exporter.get_finished_logs()]
        assert len(bodies) == 1
        _assert_redacted(bodies[0])

    def test_structlog_json_passes_through_unchanged(self, capsys: pytest.CaptureFixture[str]) -> None:
        setup_logger("INFO").warning("Produced event", key=5, topic="execution.requested")

        line = next(line for line in capsys.readouterr().err.splitlines() if "Produced event" in line)
        payload = json.loads(line)
        assert payload["key"] == 5
        assert payload["topic"] == "execution.requested"

    @pytest.mark.parametrize(
        ("root_level", "expected_level"),
        [("DEBUG", logging.WARNING), ("INFO", logging.WARNING), ("ERROR", logging.ERROR)],
    )
    def test_third_party_loggers_stay_quiet(
        self,
        root_level: str,
        expected_level: int,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        setup_logger(root_level)
        logging.getLogger("pymongo.command").info("find users {'hashed_password': 'x'}")

        assert logging.getLogger("pymongo.command").getEffectiveLevel() == expected_level
        assert logging.getLogger("aiokafka.conn").getEffectiveLevel() == expected_level
        assert "find users" not in capsys.readouterr().err


class TestTypedSecrets:
    """Secrets are SecretStr, so they stay masked however deep a log call nests them."""

    def test_nested_secrets_stay_masked(self, test_settings: Settings, capsys: pytest.CaptureFixture[str]) -> None:
        user = UserDocument(username="alice", email="alice@example.com", hashed_password="$2b$04$nested.hash.value")
        login = LoginResult(
            username="alice",
            role=UserRole.USER,
            access_token=SecretStr("eyJ.nested.access"),
            csrf_token=SecretStr("nonce.nested.csrf"),
            session_timeout_minutes=60,
        )

        setup_logger("INFO").info(
            "Nested secrets", context={"users": [user], "login": login, "settings": test_settings}
        )

        line = next(line for line in capsys.readouterr().err.splitlines() if "Nested secrets" in line)
        secrets = [
            "$2b$04$nested.hash.value",
            "eyJ.nested.access",
            "nonce.nested.csrf",
            test_settings.SECRET_KEY.get_secret_value(),
            test_settings.MONGO_PASSWORD.get_secret_value(),
            test_settings.REDIS_PASSWORD.get_secret_value(),
        ]
        assert [secret for secret in secrets if secret in line] == []
        assert line.count("**********") >= 6
