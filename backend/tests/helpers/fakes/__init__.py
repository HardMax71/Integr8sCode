"""Fake implementations for external boundary clients used in tests."""

from .providers import FakeBoundaryClientProvider, FakeDatabaseProvider, FakeSchemaRegistryProvider
from .schema_registry import FakeSchemaRegistryManager

__all__ = [
    "FakeBoundaryClientProvider",
    "FakeDatabaseProvider",
    "FakeSchemaRegistryManager",
    "FakeSchemaRegistryProvider",
]
