import json
import logging
import io
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.core.correlation import CorrelationContext, CorrelationMiddleware
from app.core.logging import CorrelationFilter, JSONFormatter, setup_logger


def capture_log(formatter: logging.Formatter, msg: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    logger = logging.getLogger("t")

    # Use StringIO to capture output
    string_io = io.StringIO()
    stream = logging.StreamHandler(string_io)
    stream.setFormatter(formatter)

    # Add the correlation filter
    correlation_filter = CorrelationFilter()
    stream.addFilter(correlation_filter)

    logger.handlers = [stream]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Log the message
    logger.info(msg, extra=extra or {})
    stream.flush()

    # Get the formatted output
    output = string_io.getvalue()
    string_io.close()

    if output:
        return json.loads(output)

    # Fallback: create and format record manually
    lr = logging.LogRecord("t", logging.INFO, __file__, 1, msg, (), None, None)
    # Apply the filter manually
    correlation_filter.filter(lr)
    s = formatter.format(lr)
    return json.loads(s)


def test_json_formatter_sanitizes_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force deterministic timestamp by monkeypatching datetime in formatter if needed
    fmt = JSONFormatter()
    msg = "Bearer abcd1234 and mongodb://user:secret@host/db and email a@b.com"
    d = capture_log(fmt, msg)
    s = d["message"]
    assert "***BEARER_TOKEN_REDACTED***" in s
    assert "***MONGODB_REDACTED***" in s
    assert "***EMAIL_REDACTED***" in s


def test_correlation_context_and_filter() -> None:
    CorrelationContext.set_correlation_id("cid-1")
    CorrelationContext.set_request_metadata({"method": "GET", "path": "/x", "client": {"host": "1.2.3.4"}})
    d = capture_log(JSONFormatter(), "hello")
    assert d["correlation_id"] == "cid-1"
    assert d["request_method"] == "GET"
    assert d["request_path"] == "/x"
    assert d["client_host"] == "1.2.3.4"
    CorrelationContext.clear()


def test_correlation_middleware_sets_header() -> None:
    app = Starlette()

    @app.route("/ping")
    async def ping(request: Request):  # type: ignore[override]
        return JSONResponse({"ok": True})

    app.add_middleware(CorrelationMiddleware)
    with TestClient(app) as client:
        r = client.get("/ping")
        assert r.status_code == 200
        # Correlation header present
        assert "X-Correlation-ID" in r.headers


def test_setup_logger_returns_logger():
    lg = setup_logger()
    assert hasattr(lg, "info")
