from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions.base import AuthenticationError, IntegrationException, ServiceError
from app.core.exceptions.handlers import configure_exception_handlers


def make_app(raise_exc):
    app = FastAPI()
    configure_exception_handlers(app)

    @app.get("/boom")
    def boom():  # type: ignore[no-redef]
        raise raise_exc

    return app


def test_integration_exception_handler():
    app = make_app(IntegrationException(418, "teapot"))
    with TestClient(app) as c:
        r = c.get("/boom")
        assert r.status_code == 418
        assert r.json()["detail"] == "teapot"


def test_authentication_error_handler():
    app = make_app(AuthenticationError("nope"))
    with TestClient(app) as c:
        r = c.get("/boom")
        assert r.status_code == 401
        assert r.json()["detail"] == "nope"


def test_service_error_handler():
    app = make_app(ServiceError("oops", status_code=503))
    with TestClient(app) as c:
        r = c.get("/boom")
        assert r.status_code == 503
        assert r.json()["detail"] == "oops"

