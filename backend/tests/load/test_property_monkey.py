from __future__ import annotations

import os
import ssl

import httpx
import pytest
from hypothesis import HealthCheck, given, settings

from .strategies import alertmanager_webhook, user_create


API = os.getenv("LOAD_API_PREFIX", "/api/v1")
VERIFY_TLS = os.getenv("LOAD_VERIFY_TLS", "false").lower() in ("1", "true", "yes")


def create_test_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


@pytest.fixture(scope="module")
def client(selected_base_url: str) -> httpx.Client:
    """Create client using the properly detected base URL."""
    c = httpx.Client(
        base_url=selected_base_url,
        verify=create_test_ssl_context() if not VERIFY_TLS else True,
        timeout=10.0
    )
    yield c
    c.close()


def api(path: str) -> str:
    """Build API path (without base URL since client has it)."""
    return f"{API.rstrip('/')}{path}"


@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(payload=user_create)
def test_register_never_500(client: httpx.Client, payload: dict) -> None:
    # Property: registering arbitrary (syntactically valid) user payload should not crash the API
    # Acceptable outcomes: 200/201 (created), 400 (already exists / validation), 422 (validation), 404 (not found)
    r = client.post(api("/auth/register"), json=payload)
    assert r.status_code not in (500, 502, 503, 504)


@settings(deadline=None, max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(payload=alertmanager_webhook)
def test_alertmanager_webhook_never_500(client: httpx.Client, payload: dict) -> None:
    # Property: alertmanager webhook must never crash under arbitrary (schema-like) payloads
    r = client.post(api("/alertmanager/webhook"), json=payload)
    assert r.status_code not in (500, 502, 503, 504)

