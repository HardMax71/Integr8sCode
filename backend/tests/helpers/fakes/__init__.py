"""Fake implementations for external boundary clients used in tests."""

from .providers import FakeBoundaryClientProvider, FakeSchemaRegistryProvider
from .schema_registry import FakeSchemaRegistryManager

__all__ = [
    "FakeBoundaryClientProvider",
    "FakeSchemaRegistryManager",
    "FakeSchemaRegistryProvider",
]
