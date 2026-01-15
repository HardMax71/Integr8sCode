# mypy: disable-error-code="slop-any-check"
"""
Validates complete correspondence between EventType enum and event classes.

This test ensures that:
1. Every EventType has a corresponding domain event class (in DomainEvent union)
2. Every EventType has a corresponding Kafka event class (DomainEvent subclass)
3. No orphan event classes exist (classes without matching EventType)

Run this test to catch missing event implementations early.
"""

from typing import get_args

from app.domain.enums.events import EventType
from app.domain.events.typed import BaseEvent, DomainEvent, domain_event_adapter
from app.events.schema.schema_registry import _get_event_type_to_class_mapping


def get_domain_event_classes() -> dict[EventType, type]:
    """Extract EventType -> class mapping from DomainEvent union."""
    mapping: dict[EventType, type] = {}
    union_types = get_args(DomainEvent)
    # First element is the actual union, need to get its args
    if union_types:
        inner = union_types[0]
        if hasattr(inner, "__args__"):
            event_classes = inner.__args__
        else:
            # Python 3.10+ union syntax
            event_classes = get_args(inner) or [inner]
            if not event_classes:
                event_classes = list(union_types[:-1])  # Exclude Discriminator
    else:
        event_classes = []

    # Fallback: iterate through all BaseEvent subclasses
    if not event_classes:
        event_classes = []
        for cls in BaseEvent.__subclasses__():
            if hasattr(cls, "model_fields") and "event_type" in cls.model_fields:
                event_classes.append(cls)

    for cls in event_classes:
        if hasattr(cls, "model_fields") and "event_type" in cls.model_fields:
            field = cls.model_fields["event_type"]
            if field.default is not None:
                mapping[field.default] = cls

    return mapping


def get_kafka_event_classes() -> dict[EventType, type]:
    """Extract EventType -> class mapping from Kafka DomainEvent subclasses."""
    return _get_event_type_to_class_mapping()


class TestEventSchemaCoverage:
    """Ensure complete correspondence between EventType and event classes."""

    def test_all_event_types_have_domain_event_class(self) -> None:
        """Every EventType must have a corresponding domain event class."""
        domain_mapping = get_domain_event_classes()
        all_types = set(EventType)
        covered_types = set(domain_mapping.keys())
        missing = all_types - covered_types

        assert not missing, (
            f"Missing domain event classes for {len(missing)} EventType(s):\n"
            + "\n".join(f"  - {et.value}: needs a class in typed.py" for et in sorted(missing, key=lambda x: x.value))
        )

    def test_all_event_types_have_kafka_event_class(self) -> None:
        """Every EventType must have a corresponding Kafka event class."""
        kafka_mapping = get_kafka_event_classes()
        all_types = set(EventType)
        covered_types = set(kafka_mapping.keys())
        missing = all_types - covered_types

        assert not missing, (
            f"Missing Kafka event classes for {len(missing)} EventType(s):\n"
            + "\n".join(
                f"  - {et.value}: needs a class in infrastructure/kafka/events/"
                for et in sorted(missing, key=lambda x: x.value)
            )
        )

    def test_domain_event_adapter_covers_all_types(self) -> None:
        """The domain_event_adapter TypeAdapter must handle all EventTypes."""
        errors: list[str] = []

        for et in EventType:
            try:
                # Validation will fail due to missing required fields, but that's OK
                # We just want to confirm the type IS in the union (not "unknown discriminator")
                domain_event_adapter.validate_python({"event_type": et})
            except Exception as e:
                error_str = str(e).lower()
                # "validation error" means type IS recognized but fields are missing - that's fine
                # "no match" or "discriminator" means type is NOT in union - that's a failure
                if "no match" in error_str or "unable to extract" in error_str:
                    errors.append(f"  - {et.value}: not in DomainEvent union")

        assert not errors, f"domain_event_adapter missing {len(errors)} type(s):\n" + "\n".join(errors)

    def test_no_orphan_domain_event_classes(self) -> None:
        """All domain event classes must have a corresponding EventType."""
        orphans: list[str] = []

        for cls in BaseEvent.__subclasses__():
            # Skip test fixtures/mocks (private classes starting with _)
            if cls.__name__.startswith("_"):
                continue
            if not hasattr(cls, "model_fields"):
                continue
            field = cls.model_fields.get("event_type")
            if field is None:
                continue
            if field.default is None:
                orphans.append(f"  - {cls.__name__}: event_type field has no default")
            elif not isinstance(field.default, EventType):
                orphans.append(f"  - {cls.__name__}: event_type default is not an EventType")

        assert not orphans, "Orphan domain event classes:\n" + "\n".join(orphans)

    def test_no_orphan_kafka_event_classes(self) -> None:
        """All Kafka event classes must have a corresponding EventType."""
        orphans: list[str] = []

        for cls in BaseEvent.__subclasses__():
            # Skip test fixtures/mocks (private classes starting with _)
            if cls.__name__.startswith("_"):
                continue
            if not hasattr(cls, "model_fields"):
                continue
            field = cls.model_fields.get("event_type")
            if field is None:
                orphans.append(f"  - {cls.__name__}: missing event_type field")
            elif field.default is None:
                orphans.append(f"  - {cls.__name__}: event_type field has no default")
            elif not isinstance(field.default, EventType):
                orphans.append(f"  - {cls.__name__}: event_type default is not an EventType")

        assert not orphans, "Orphan Kafka event classes:\n" + "\n".join(orphans)

    def test_domain_and_kafka_event_names_match(self) -> None:
        """Domain and Kafka event classes for same EventType should have same name."""
        domain_mapping = get_domain_event_classes()
        kafka_mapping = get_kafka_event_classes()

        mismatches: list[str] = []
        for et in EventType:
            domain_cls = domain_mapping.get(et)
            kafka_cls = kafka_mapping.get(et)

            if domain_cls and kafka_cls:
                if domain_cls.__name__ != kafka_cls.__name__:
                    mismatches.append(
                        f"  - {et.value}: domain={domain_cls.__name__}, kafka={kafka_cls.__name__}"
                    )

        assert not mismatches, (
            f"Event class name mismatches for {len(mismatches)} type(s):\n" + "\n".join(mismatches)
        )


class TestEventSchemaConsistency:
    """Additional consistency checks between domain and Kafka event schemas."""

    def test_event_type_count_sanity(self) -> None:
        """Sanity check: we should have a reasonable number of event types."""
        count = len(EventType)
        assert count >= 50, f"Expected at least 50 EventTypes, got {count}"

    def test_all_event_types_are_lowercase_snake_case(self) -> None:
        """All EventType values should be lowercase snake_case."""
        violations: list[str] = []
        for et in EventType:
            value = et.value
            if value != value.lower():
                violations.append(f"  - {et.name}: '{value}' contains uppercase")
            if " " in value or "-" in value:
                violations.append(f"  - {et.name}: '{value}' contains spaces or hyphens")

        assert not violations, "EventType naming violations:\n" + "\n".join(violations)
