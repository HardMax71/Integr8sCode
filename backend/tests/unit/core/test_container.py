from types import SimpleNamespace

from app.core import container as container_mod


def test_create_app_container_uses_make_async_container(monkeypatch):
    captured = {}

    def fake_make_async_container(*providers):  # noqa: ANN001
        captured["count"] = len(providers)
        return SimpleNamespace(name="container")

    monkeypatch.setattr(container_mod, "make_async_container", fake_make_async_container)
    c = container_mod.create_app_container()
    assert getattr(c, "name") == "container"
    assert captured["count"] > 0

