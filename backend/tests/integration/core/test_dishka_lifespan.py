from fastapi import FastAPI


def test_lifespan_container_attached(app: FastAPI) -> None:
    # App fixture uses real lifespan; container is attached to app.state
    assert isinstance(app, FastAPI)
    assert hasattr(app.state, "dishka_container")


def test_create_app_attaches_container() -> None:
    from importlib import import_module
    app = import_module("app.main").create_app()
    assert isinstance(app, FastAPI)
    assert hasattr(app.state, "dishka_container")
