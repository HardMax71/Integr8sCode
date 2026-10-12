"""Every API field and enum value has one name, the one the spec carries, and nothing renames it."""

import pkgutil
from importlib import import_module
from typing import Any

import pytest
from beanie import Document
from pydantic import BaseModel

import app as app_package
from app.core.utils import StringEnum
from app.main import create_app
from app.settings import Settings

pytestmark = pytest.mark.unit

# FastAPI's own validation error model titles its fields ("msg" is "Message")
_FRAMEWORK_SCHEMAS = {"ValidationError", "HTTPValidationError"}


def _subclasses[T](base: type[T]) -> set[type[T]]:
    for module in pkgutil.walk_packages(app_package.__path__, "app."):
        import_module(module.name)
    found: set[type[T]] = set()
    pending = [base]
    while pending:
        for sub in pending.pop().__subclasses__():
            if sub not in found:
                found.add(sub)
                pending.append(sub)
    return found


@pytest.fixture(scope="module")
def spec(test_settings: Settings) -> dict[str, Any]:
    return create_app(settings=test_settings).openapi()


def test_property_titles_are_their_keys(spec: dict[str, Any]) -> None:
    renamed = [
        (schema_name, key, prop["title"])
        for schema_name, schema in spec["components"]["schemas"].items()
        if schema_name not in _FRAMEWORK_SCHEMAS
        for key, prop in schema.get("properties", {}).items()
        if "title" in prop and prop["title"] != key.title().replace("_", " ")
    ]
    assert renamed == []


def test_models_have_no_aliases() -> None:
    aliased = [
        f"{model.__module__}.{model.__qualname__}.{name}"
        for model in _subclasses(BaseModel)
        if model.__module__.startswith("app.")
        for name, field in model.model_fields.items()
        if {field.alias, field.validation_alias, field.serialization_alias} - {None, name}
        and not (issubclass(model, Document) and name == "id")  # Beanie maps it to Mongo's _id
    ]
    assert aliased == []


def test_enum_members_are_named_after_their_values() -> None:
    renamed = [
        f"{enum.__qualname__}.{member.name} = {member.value!r}"
        for enum in _subclasses(StringEnum)
        for member in enum
        if member.name.lower() != member.value.lower()
    ]
    assert renamed == []
