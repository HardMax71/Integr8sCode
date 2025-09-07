from enum import auto

from starlette.requests import Request

from app.core.utils import StringEnum, get_client_ip


class E(StringEnum):
    A = "a"
    B = "b"


def test_string_enum_str_repr_format() -> None:
    assert str(E.A) == "a"
    assert repr(E.B) == "b"
    assert f"{E.A}" == "a"


def make_request(headers: dict[str, str] | None = None, client_ip: str | None = None) -> Request:
    headers = headers or {}
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.encode().lower(), v.encode()) for k, v in headers.items()],
        "client": (client_ip, 1234) if client_ip else None,
    }
    return Request(scope)


def test_get_client_ip_header_precedence() -> None:
    r = make_request({"x-forwarded-for": "9.9.9.9, 8.8.8.8"})
    assert get_client_ip(r) == "9.9.9.9"
    r2 = make_request({"x-real-ip": "7.7.7.7"})
    assert get_client_ip(r2) == "7.7.7.7"
    r3 = make_request({}, client_ip="1.2.3.4")
    assert get_client_ip(r3) == "1.2.3.4"

