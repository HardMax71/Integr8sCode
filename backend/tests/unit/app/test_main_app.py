import pytest
from fastapi import FastAPI

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def patch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    class S:  # minimal settings shim
        PROJECT_NAME = "test"
        API_V1_STR = "/api/v1"
        TESTING = True
        SERVER_HOST = "127.0.0.1"
        SERVER_PORT = 443
        SSL_KEYFILE = "k"
        SSL_CERTFILE = "c"
        WEB_CONCURRENCY = 1
        WEB_BACKLOG = 10
        WEB_TIMEOUT = 10

    monkeypatch.setattr("app.main.get_settings", lambda: S())


@pytest.fixture(autouse=True)
def patch_di_and_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    # Just use the real dishka - it's already installed!
    # Only patch the container creation to return a mock container
    from dishka import AsyncContainer

    class MockContainer(AsyncContainer):
        def __init__(self, *args, **kwargs):
            pass  # Don't actually initialize the real container

    # Patch only the container creation
    monkeypatch.setattr("app.core.container.create_app_container", lambda: MockContainer(), raising=False)
    # Metrics no-op
    monkeypatch.setattr("app.core.middlewares.metrics.setup_metrics", lambda app: None)


def test_create_app_builds_fastapi_instance() -> None:
    # Import after patching
    from app import main as mainmod
    app: FastAPI = mainmod.create_app()
    assert isinstance(app, FastAPI)

    # Routers included (check some path prefixes exist)
    paths = {r.path for r in app.router.routes}
    # Expected to include API v1 routes. Assert at least base prefix present in some routes.
    assert any(p.startswith("/api/") for p in paths)

    # Middlewares include CORS and our custom ones
    mids = [m.cls.__name__ for m in app.user_middleware]
    assert "CORSMiddleware" in mids
    # CorrelationMiddleware, RequestSizeLimitMiddleware, CacheControlMiddleware added
    assert any("Correlation" in n for n in mids)
    assert any("RequestSizeLimit" in n for n in mids)
    assert any("CacheControl" in n for n in mids)
