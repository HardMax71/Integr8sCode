"""
Validates event class topic naming conventions for 1:1 topic mapping.

This test ensures that:
1. All BaseEvent subclasses have proper topic() classmethod
2. Topic names are derived correctly from class names (snake_case, no 'Event' suffix)
3. No duplicate topic names exist

Run this test to catch event naming issues early.
"""

import re

from app.domain.events.typed import BaseEvent


def get_all_event_classes() -> list[type[BaseEvent]]:
    """Get all BaseEvent subclasses."""
    classes: list[type[BaseEvent]] = []

    def collect_subclasses(cls: type) -> None:
        for subclass in cls.__subclasses__():
            if subclass.__name__.startswith("_"):
                continue
            classes.append(subclass)
            collect_subclasses(subclass)

    collect_subclasses(BaseEvent)
    return classes


class TestEventTopicCoverage:
    """Ensure proper topic naming for all event classes."""

    def test_all_event_classes_have_topic_method(self) -> None:
        """Every BaseEvent subclass must have a topic() classmethod."""
        errors: list[str] = []

        for cls in get_all_event_classes():
            if not hasattr(cls, "topic"):
                errors.append(f"  - {cls.__name__}: missing topic() classmethod")
            elif not callable(cls.topic):
                errors.append(f"  - {cls.__name__}: topic is not callable")

        assert not errors, "Event classes missing topic():\n" + "\n".join(errors)

    def test_all_topics_are_snake_case(self) -> None:
        """All topic names should be lowercase snake_case."""
        violations: list[str] = []

        for cls in get_all_event_classes():
            topic = cls.topic()
            if topic != topic.lower():
                violations.append(f"  - {cls.__name__}: topic '{topic}' contains uppercase")
            if " " in topic or "-" in topic:
                violations.append(f"  - {cls.__name__}: topic '{topic}' contains spaces or hyphens")
            if not re.match(r"^[a-z][a-z0-9_]*$", topic):
                violations.append(f"  - {cls.__name__}: topic '{topic}' has invalid format")

        assert not violations, "Topic naming violations:\n" + "\n".join(violations)

    def test_no_duplicate_topics(self) -> None:
        """All event classes must have unique topic names."""
        topic_to_classes: dict[str, list[str]] = {}

        for cls in get_all_event_classes():
            topic = cls.topic()
            if topic not in topic_to_classes:
                topic_to_classes[topic] = []
            topic_to_classes[topic].append(cls.__name__)

        duplicates = {t: classes for t, classes in topic_to_classes.items() if len(classes) > 1}

        assert not duplicates, (
            "Duplicate topic names found:\n"
            + "\n".join(f"  - {topic}: {', '.join(classes)}" for topic, classes in duplicates.items())
        )

    def test_topic_derived_from_class_name(self) -> None:
        """Topic names should be derived from class names (snake_case, no 'Event' suffix)."""
        errors: list[str] = []

        for cls in get_all_event_classes():
            topic = cls.topic()
            class_name = cls.__name__

            # Expected: remove 'Event' suffix and convert to snake_case
            expected_base = class_name.removesuffix("Event")
            # Convert PascalCase to snake_case
            expected_topic = re.sub(r"(?<!^)(?=[A-Z])", "_", expected_base).lower()

            if topic != expected_topic:
                errors.append(f"  - {class_name}: expected topic '{expected_topic}', got '{topic}'")

        assert not errors, "Topic naming mismatches:\n" + "\n".join(errors)


class TestEventClassCount:
    """Sanity checks for event class coverage."""

    def test_event_class_count_sanity(self) -> None:
        """Sanity check: we should have a reasonable number of event classes."""
        count = len(get_all_event_classes())
        assert count >= 10, f"Expected at least 10 event classes, got {count}"
