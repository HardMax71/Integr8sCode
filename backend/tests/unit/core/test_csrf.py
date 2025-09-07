import pytest
from starlette.requests import Request

from app.core.security import validate_csrf_token, security_service


def make_request(method: str, path: str, headers: dict[str, str] | None = None, cookies: dict[str, str] | None = None) -> Request:
    headers = headers or {}
    if cookies:
        cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers = {**headers, "cookie": cookie_header}
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    return Request(scope)


def test_csrf_skips_on_get() -> None:
    req = make_request("GET", "/api/v1/anything")
    assert validate_csrf_token(req) == "skip"


def test_csrf_missing_header_raises_when_authenticated() -> None:
    req = make_request("POST", "/api/v1/items", cookies={"access_token": "tok", "csrf_token": "abc"})
    with pytest.raises(Exception):
        validate_csrf_token(req)


def test_csrf_valid_tokens() -> None:
    token = security_service.generate_csrf_token()
    req = make_request(
        "POST",
        "/api/v1/items",
        headers={"X-CSRF-Token": token},
        cookies={"access_token": "tok", "csrf_token": token},
    )
    assert validate_csrf_token(req) == token
