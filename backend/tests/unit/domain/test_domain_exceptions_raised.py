import ast
import importlib
import pkgutil
from collections.abc import Iterator
from pathlib import Path

import pytest

import app
from app.domain.exceptions import DomainError

pytestmark = pytest.mark.unit

_APP_DIR = Path(app.__file__).parent


def _subclasses(cls: type[DomainError]) -> Iterator[type[DomainError]]:
    for sub in cls.__subclasses__():
        yield sub
        yield from _subclasses(sub)


def _raised_names() -> set[str]:
    names: set[str] = set()
    for path in _APP_DIR.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Attribute):
                names.add(target.attr)
    return names


def test_every_domain_specific_exception_is_raised_somewhere() -> None:
    for module in pkgutil.walk_packages(app.__path__, "app."):
        importlib.import_module(module.name)
    specific = {
        cls.__name__
        for cls in _subclasses(DomainError)
        if cls.__module__.startswith("app.domain.") and cls.__module__ != "app.domain.exceptions"
    }

    assert specific
    assert sorted(specific - _raised_names()) == []
