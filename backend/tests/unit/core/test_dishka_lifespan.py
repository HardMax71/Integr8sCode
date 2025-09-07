import asyncio
import types

import pytest
from fastapi import FastAPI

from app.core import dishka_lifespan as lf


class StubSchemaRegistry:
    async def init(self):
        return None


class StubSchemaManager:
    def __init__(self, db):  # noqa: ANN001
        pass

    async def apply_all(self):
        return None


class StubContainer:
    async def get(self, t):  # noqa: ANN001
        # Return simple stubs based on requested type name
        return object()


@pytest.mark.asyncio
async def test_lifespan_runs_with_patched_dependencies(monkeypatch):
    app = FastAPI()
    app.state.dishka_container = StubContainer()

    # Patch settings
    class S:
        PROJECT_NAME = "t"
        TESTING = True
        TRACING_SERVICE_NAME = "svc"
        TRACING_SERVICE_VERSION = "1"
        TRACING_SAMPLING_RATE = 0.1
        TRACING_ADAPTIVE_SAMPLING = False

    monkeypatch.setattr(lf, "get_settings", lambda: S())

    # Patch tracing to return report object
    class R:
        def has_failures(self):
            return False

        def get_summary(self):
            return "ok"

    monkeypatch.setattr(lf, "init_tracing", lambda **kwargs: R())

    # Patch schema registry and DB schema
    monkeypatch.setattr(lf, "SchemaManager", StubSchemaManager)
    monkeypatch.setattr(lf, "initialize_event_schemas", lambda *args, **kwargs: asyncio.sleep(0))

    # Patch metrics and rate limits
    monkeypatch.setattr(lf, "initialize_metrics_context", lambda container: asyncio.sleep(0))
    monkeypatch.setattr(lf, "initialize_rate_limits", lambda client, settings: asyncio.sleep(0))

    # Patch SSE router fetch to no-op
    class DummyRouter:
        pass

    monkeypatch.setattr(lf, "PartitionedSSERouter", DummyRouter)

    # Run lifespan context
    async with lf.lifespan(app):
        pass

