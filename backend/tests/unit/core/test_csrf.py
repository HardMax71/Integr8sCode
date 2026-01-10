import pytest
from app.core.security import SecurityService
from app.settings import Settings
from starlette.requests import Request


def make_request(method: str, path: str, headers: dict[str, str] | None = None,
                 cookies: dict[str, str] | None = None) -> Request:
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


def test_csrf_skips_on_get(test_settings: Settings) -> None:
    security_service = SecurityService(test_settings)
    req = make_request("GET", "/api/v1/anything")
    assert security_service.validate_csrf_from_request(req) == "skip"


def test_csrf_missing_header_raises_when_authenticated(test_settings: Settings) -> None:
    security_service = SecurityService(test_settings)
    req = make_request("POST", "/api/v1/items", cookies={"access_token": "tok", "csrf_token": "abc"})
    with pytest.raises(Exception):
        security_service.validate_csrf_from_request(req)


def test_csrf_valid_tokens(test_settings: Settings) -> None:
    security_service = SecurityService(test_settings)
    token = security_service.generate_csrf_token()
    req = make_request(
        "POST",
        "/api/v1/items",
        headers={"X-CSRF-Token": token},
        cookies={"access_token": "tok", "csrf_token": token},
    )
    assert security_service.validate_csrf_from_request(req) == token
