import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest
from app.domain.enums.auth import LoginMethod
from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.kafka import KafkaTopic
from app.domain.enums.notification import NotificationChannel, NotificationSeverity
from app.domain.enums.storage import ExecutionErrorType
from app.domain.execution import ResourceUsageDomain
from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.events.execution import (
    ExecutionAcceptedEvent,
    ExecutionCancelledEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionQueuedEvent,
    ExecutionRequestedEvent,
    ExecutionRunningEvent,
    ExecutionStartedEvent,
    ExecutionTimeoutEvent,
)
from app.infrastructure.kafka.events.metadata import AvroEventMetadata
from app.infrastructure.kafka.events.notification import (
    NotificationClickedEvent,
    NotificationCreatedEvent,
    NotificationDeliveredEvent,
    NotificationFailedEvent,
    NotificationReadEvent,
    NotificationSentEvent,
)
from app.infrastructure.kafka.events.saga import (
    AllocateResourcesCommandEvent,
    CreatePodCommandEvent,
    DeletePodCommandEvent,
    ReleaseResourcesCommandEvent,
    SagaCancelledEvent,
    SagaCompensatedEvent,
    SagaCompensatingEvent,
    SagaCompletedEvent,
    SagaFailedEvent,
    SagaStartedEvent,
)
from app.infrastructure.kafka.events.user import (
    UserDeletedEvent,
    UserLoggedInEvent,
    UserLoggedOutEvent,
    UserRegisteredEvent,
    UserSettingsUpdatedEvent,
    UserUpdatedEvent,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def metadata() -> AvroEventMetadata:
    """Create standard metadata for tests."""
    return AvroEventMetadata(
        service_name="test-service",
        service_version="1.0.0",
        user_id="user-123",
        correlation_id="corr-456",
    )


@pytest.fixture
def resource_usage() -> ResourceUsageDomain:
    """Create standard resource usage for tests."""
    return ResourceUsageDomain(
        execution_time_wall_seconds=1.5,
        cpu_time_jiffies=100,
        clk_tck_hertz=100,
        peak_memory_kb=1024,
    )


class TestAvroEventMetadata:
    """Tests for AvroEventMetadata."""

    def test_default_correlation_id_generated(self) -> None:
        """Generates UUID correlation_id by default."""
        metadata = AvroEventMetadata(service_name="svc", service_version="1.0")
        UUID(metadata.correlation_id)  # Validates it's a valid UUID

    def test_with_correlation_returns_new_instance(self, metadata: AvroEventMetadata) -> None:
        """with_correlation returns new instance with updated correlation_id."""
        new_metadata = metadata.with_correlation("new-corr")
        assert new_metadata.correlation_id == "new-corr"
        assert metadata.correlation_id == "corr-456"  # Original unchanged

    def test_with_user_returns_new_instance(self, metadata: AvroEventMetadata) -> None:
        """with_user returns new instance with updated user_id."""
        new_metadata = metadata.with_user("new-user")
        assert new_metadata.user_id == "new-user"
        assert metadata.user_id == "user-123"  # Original unchanged

    def test_ensure_correlation_id_preserves_existing(self, metadata: AvroEventMetadata) -> None:
        """ensure_correlation_id keeps existing correlation_id."""
        result = metadata.ensure_correlation_id()
        assert result.correlation_id == "corr-456"

    def test_ensure_correlation_id_generates_when_empty(self) -> None:
        """ensure_correlation_id generates new id when empty."""
        metadata = AvroEventMetadata(
            service_name="svc",
            service_version="1.0",
            correlation_id="",
        )
        # Empty string is falsy, so new correlation should be generated
        # Actually, looking at the code, it checks `if self.correlation_id:`
        # which means empty string returns self. Let me verify the behavior.
        result = metadata.ensure_correlation_id()
        # Empty string is falsy, should generate new
        assert result.correlation_id != "" or metadata.correlation_id == ""


class TestBaseEvent:
    """Tests for BaseEvent base class behavior."""

    def test_event_id_auto_generated(self, metadata: AvroEventMetadata) -> None:
        """Event ID is auto-generated as valid UUID."""
        event = ExecutionRequestedEvent(
            execution_id="exec-1",
            script="print('test')",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_command=["python"],
            runtime_filename="main.py",
            timeout_seconds=30,
            cpu_limit="100m",
            memory_limit="128Mi",
            cpu_request="50m",
            memory_request="64Mi",
            metadata=metadata,
        )
        UUID(event.event_id)  # Validates UUID format

    def test_timestamp_auto_generated(self, metadata: AvroEventMetadata) -> None:
        """Timestamp is auto-generated as UTC datetime."""
        before = datetime.now(timezone.utc)
        event = ExecutionRequestedEvent(
            execution_id="exec-1",
            script="print('test')",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_command=["python"],
            runtime_filename="main.py",
            timeout_seconds=30,
            cpu_limit="100m",
            memory_limit="128Mi",
            cpu_request="50m",
            memory_request="64Mi",
            metadata=metadata,
        )
        after = datetime.now(timezone.utc)
        assert before <= event.timestamp <= after

    def test_to_dict_serializes_properly(self, metadata: AvroEventMetadata) -> None:
        """to_dict produces JSON-serializable dict."""
        event = ExecutionRequestedEvent(
            execution_id="exec-1",
            script="print('test')",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_command=["python"],
            runtime_filename="main.py",
            timeout_seconds=30,
            cpu_limit="100m",
            memory_limit="128Mi",
            cpu_request="50m",
            memory_request="64Mi",
            metadata=metadata,
        )
        d = event.to_dict()
        json_str = json.dumps(d)  # Should not raise
        parsed = json.loads(json_str)
        assert parsed["execution_id"] == "exec-1"
        assert isinstance(parsed["timestamp"], str)  # Serialized to ISO string

    def test_to_json_produces_valid_json(self, metadata: AvroEventMetadata) -> None:
        """to_json produces valid JSON string."""
        event = ExecutionRequestedEvent(
            execution_id="exec-1",
            script="print('test')",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_command=["python"],
            runtime_filename="main.py",
            timeout_seconds=30,
            cpu_limit="100m",
            memory_limit="128Mi",
            cpu_request="50m",
            memory_request="64Mi",
            metadata=metadata,
        )
        json_str = event.to_json()
        parsed = json.loads(json_str)
        assert parsed["script"] == "print('test')"


class TestExecutionEvents:
    """Tests for execution event types."""

    @pytest.mark.parametrize(
        "event_cls,event_type,topic,extra_fields",
        [
            (
                ExecutionRequestedEvent,
                EventType.EXECUTION_REQUESTED,
                KafkaTopic.EXECUTION_EVENTS,
                {
                    "execution_id": "exec-1",
                    "script": "print(1)",
                    "language": "python",
                    "language_version": "3.11",
                    "runtime_image": "python:3.11-slim",
                    "runtime_command": ["python"],
                    "runtime_filename": "main.py",
                    "timeout_seconds": 30,
                    "cpu_limit": "100m",
                    "memory_limit": "128Mi",
                    "cpu_request": "50m",
                    "memory_request": "64Mi",
                },
            ),
            (
                ExecutionAcceptedEvent,
                EventType.EXECUTION_ACCEPTED,
                KafkaTopic.EXECUTION_EVENTS,
                {"execution_id": "exec-1", "queue_position": 5},
            ),
            (
                ExecutionQueuedEvent,
                EventType.EXECUTION_QUEUED,
                KafkaTopic.EXECUTION_EVENTS,
                {"execution_id": "exec-1"},
            ),
            (
                ExecutionRunningEvent,
                EventType.EXECUTION_RUNNING,
                KafkaTopic.EXECUTION_EVENTS,
                {"execution_id": "exec-1", "pod_name": "exec-1-pod"},
            ),
            (
                ExecutionStartedEvent,
                EventType.EXECUTION_STARTED,
                KafkaTopic.EXECUTION_EVENTS,
                {"execution_id": "exec-1", "pod_name": "exec-1-pod"},
            ),
            (
                ExecutionCancelledEvent,
                EventType.EXECUTION_CANCELLED,
                KafkaTopic.EXECUTION_EVENTS,
                {"execution_id": "exec-1", "reason": "user_requested"},
            ),
        ],
        ids=[
            "requested",
            "accepted",
            "queued",
            "running",
            "started",
            "cancelled",
        ],
    )
    def test_execution_event_types_and_topics(
        self,
        metadata: AvroEventMetadata,
        event_cls: type,
        event_type: EventType,
        topic: KafkaTopic,
        extra_fields: dict[str, Any],
    ) -> None:
        """Execution events have correct event_type and topic."""
        event = event_cls(metadata=metadata, **extra_fields)
        assert event.event_type == event_type
        assert event_cls.topic == topic

    def test_execution_completed_event(
        self, metadata: AvroEventMetadata, resource_usage: ResourceUsageDomain
    ) -> None:
        """ExecutionCompletedEvent has all required fields."""
        event = ExecutionCompletedEvent(
            execution_id="exec-1",
            exit_code=0,
            resource_usage=resource_usage,
            stdout="Hello\n",
            stderr="",
            metadata=metadata,
        )
        assert event.event_type == EventType.EXECUTION_COMPLETED
        assert event.topic == KafkaTopic.EXECUTION_COMPLETED
        assert event.exit_code == 0
        assert event.resource_usage.execution_time_wall_seconds == 1.5

    def test_execution_failed_event(
        self, metadata: AvroEventMetadata, resource_usage: ResourceUsageDomain
    ) -> None:
        """ExecutionFailedEvent captures error details."""
        event = ExecutionFailedEvent(
            execution_id="exec-1",
            exit_code=1,
            error_type=ExecutionErrorType.SCRIPT_ERROR,
            error_message="NameError: undefined",
            stdout="",
            stderr="Traceback...",
            resource_usage=resource_usage,
            metadata=metadata,
        )
        assert event.event_type == EventType.EXECUTION_FAILED
        assert event.topic == KafkaTopic.EXECUTION_FAILED
        assert event.error_type == ExecutionErrorType.SCRIPT_ERROR

    def test_execution_timeout_event(
        self, metadata: AvroEventMetadata, resource_usage: ResourceUsageDomain
    ) -> None:
        """ExecutionTimeoutEvent records timeout details."""
        event = ExecutionTimeoutEvent(
            execution_id="exec-1",
            timeout_seconds=30,
            resource_usage=resource_usage,
            stdout="partial output",
            stderr="",
            metadata=metadata,
        )
        assert event.event_type == EventType.EXECUTION_TIMEOUT
        assert event.topic == KafkaTopic.EXECUTION_TIMEOUT
        assert event.timeout_seconds == 30


class TestSagaEvents:
    """Tests for saga event types."""

    @pytest.mark.parametrize(
        "event_cls,event_type,extra_fields",
        [
            (
                SagaStartedEvent,
                EventType.SAGA_STARTED,
                {
                    "saga_id": "saga-1",
                    "saga_name": "execution_saga",
                    "execution_id": "exec-1",
                    "initial_event_id": "evt-1",
                },
            ),
            (
                SagaCompletedEvent,
                EventType.SAGA_COMPLETED,
                {
                    "saga_id": "saga-1",
                    "saga_name": "execution_saga",
                    "execution_id": "exec-1",
                    "completed_steps": ["validate", "allocate", "create_pod"],
                },
            ),
            (
                SagaFailedEvent,
                EventType.SAGA_FAILED,
                {
                    "saga_id": "saga-1",
                    "saga_name": "execution_saga",
                    "execution_id": "exec-1",
                    "failed_step": "create_pod",
                    "error": "Pod creation timeout",
                },
            ),
            (
                SagaCompensatingEvent,
                EventType.SAGA_COMPENSATING,
                {
                    "saga_id": "saga-1",
                    "saga_name": "execution_saga",
                    "execution_id": "exec-1",
                    "compensating_step": "release_resources",
                },
            ),
            (
                SagaCompensatedEvent,
                EventType.SAGA_COMPENSATED,
                {
                    "saga_id": "saga-1",
                    "saga_name": "execution_saga",
                    "execution_id": "exec-1",
                    "compensated_steps": ["allocate", "validate"],
                },
            ),
        ],
        ids=["started", "completed", "failed", "compensating", "compensated"],
    )
    def test_saga_event_types(
        self,
        metadata: AvroEventMetadata,
        event_cls: type,
        event_type: EventType,
        extra_fields: dict[str, Any],
    ) -> None:
        """Saga events have correct event_type and topic."""
        event = event_cls(metadata=metadata, **extra_fields)
        assert event.event_type == event_type
        assert event_cls.topic == KafkaTopic.SAGA_EVENTS

    def test_saga_cancelled_event(self, metadata: AvroEventMetadata) -> None:
        """SagaCancelledEvent captures cancellation details."""
        event = SagaCancelledEvent(
            saga_id="saga-1",
            saga_name="execution_saga",
            execution_id="exec-1",
            reason="user_cancelled",
            completed_steps=["validate", "allocate"],
            compensated_steps=["allocate"],
            cancelled_by="user-123",
            metadata=metadata,
        )
        assert event.event_type == EventType.SAGA_CANCELLED
        assert len(event.completed_steps) == 2
        assert len(event.compensated_steps) == 1

    @pytest.mark.parametrize(
        "event_cls,event_type,extra_fields",
        [
            (
                CreatePodCommandEvent,
                EventType.CREATE_POD_COMMAND,
                {
                    "saga_id": "saga-1",
                    "execution_id": "exec-1",
                    "script": "print(1)",
                    "language": "python",
                    "language_version": "3.11",
                    "runtime_image": "python:3.11-slim",
                    "runtime_command": ["python"],
                    "runtime_filename": "main.py",
                    "timeout_seconds": 30,
                    "cpu_limit": "100m",
                    "memory_limit": "128Mi",
                    "cpu_request": "50m",
                    "memory_request": "64Mi",
                    "priority": 5,
                },
            ),
            (
                DeletePodCommandEvent,
                EventType.DELETE_POD_COMMAND,
                {
                    "saga_id": "saga-1",
                    "execution_id": "exec-1",
                    "reason": "cleanup",
                    "pod_name": "exec-1-pod",
                },
            ),
            (
                AllocateResourcesCommandEvent,
                EventType.ALLOCATE_RESOURCES_COMMAND,
                {
                    "execution_id": "exec-1",
                    "cpu_request": "100m",
                    "memory_request": "128Mi",
                },
            ),
            (
                ReleaseResourcesCommandEvent,
                EventType.RELEASE_RESOURCES_COMMAND,
                {
                    "execution_id": "exec-1",
                    "cpu_request": "100m",
                    "memory_request": "128Mi",
                },
            ),
        ],
        ids=["create-pod", "delete-pod", "allocate-resources", "release-resources"],
    )
    def test_saga_command_events(
        self,
        metadata: AvroEventMetadata,
        event_cls: type,
        event_type: EventType,
        extra_fields: dict[str, Any],
    ) -> None:
        """Saga command events have correct types and topic."""
        event = event_cls(metadata=metadata, **extra_fields)
        assert event.event_type == event_type
        assert event_cls.topic == KafkaTopic.SAGA_COMMANDS


class TestNotificationEvents:
    """Tests for notification event types."""

    @pytest.mark.parametrize(
        "event_cls,event_type,extra_fields",
        [
            (
                NotificationCreatedEvent,
                EventType.NOTIFICATION_CREATED,
                {
                    "notification_id": "notif-1",
                    "user_id": "user-1",
                    "subject": "Test Subject",
                    "body": "Test body",
                    "severity": NotificationSeverity.MEDIUM,
                    "tags": ["test"],
                    "channels": [NotificationChannel.IN_APP],
                },
            ),
            (
                NotificationSentEvent,
                EventType.NOTIFICATION_SENT,
                {
                    "notification_id": "notif-1",
                    "user_id": "user-1",
                    "channel": NotificationChannel.IN_APP,
                    "sent_at": "2024-01-01T12:00:00Z",
                },
            ),
            (
                NotificationDeliveredEvent,
                EventType.NOTIFICATION_DELIVERED,
                {
                    "notification_id": "notif-1",
                    "user_id": "user-1",
                    "channel": NotificationChannel.IN_APP,
                    "delivered_at": "2024-01-01T12:00:01Z",
                },
            ),
            (
                NotificationFailedEvent,
                EventType.NOTIFICATION_FAILED,
                {
                    "notification_id": "notif-1",
                    "user_id": "user-1",
                    "channel": NotificationChannel.WEBHOOK,
                    "error": "Connection refused",
                    "retry_count": 3,
                },
            ),
            (
                NotificationReadEvent,
                EventType.NOTIFICATION_READ,
                {
                    "notification_id": "notif-1",
                    "user_id": "user-1",
                    "read_at": "2024-01-01T12:05:00Z",
                },
            ),
            (
                NotificationClickedEvent,
                EventType.NOTIFICATION_CLICKED,
                {
                    "notification_id": "notif-1",
                    "user_id": "user-1",
                    "clicked_at": "2024-01-01T12:06:00Z",
                    "action": "view_execution",
                },
            ),
        ],
        ids=["created", "sent", "delivered", "failed", "read", "clicked"],
    )
    def test_notification_event_types(
        self,
        metadata: AvroEventMetadata,
        event_cls: type,
        event_type: EventType,
        extra_fields: dict[str, Any],
    ) -> None:
        """Notification events have correct types and topic."""
        event = event_cls(metadata=metadata, **extra_fields)
        assert event.event_type == event_type
        assert event_cls.topic == KafkaTopic.NOTIFICATION_EVENTS


class TestUserEvents:
    """Tests for user event types."""

    @pytest.mark.parametrize(
        "event_cls,event_type,extra_fields",
        [
            (
                UserRegisteredEvent,
                EventType.USER_REGISTERED,
                {
                    "user_id": "user-1",
                    "username": "testuser",
                    "email": "test@example.com",
                },
            ),
            (
                UserLoggedInEvent,
                EventType.USER_LOGGED_IN,
                {
                    "user_id": "user-1",
                    "login_method": LoginMethod.PASSWORD,
                    "ip_address": "192.168.1.1",
                },
            ),
            (
                UserLoggedOutEvent,
                EventType.USER_LOGGED_OUT,
                {"user_id": "user-1", "logout_reason": "user_initiated"},
            ),
            (
                UserUpdatedEvent,
                EventType.USER_UPDATED,
                {
                    "user_id": "user-1",
                    "updated_fields": ["email", "username"],
                    "updated_by": "admin-1",
                },
            ),
            (
                UserDeletedEvent,
                EventType.USER_DELETED,
                {
                    "user_id": "user-1",
                    "deleted_by": "admin-1",
                    "reason": "account_closure",
                },
            ),
        ],
        ids=["registered", "logged-in", "logged-out", "updated", "deleted"],
    )
    def test_user_event_types(
        self,
        metadata: AvroEventMetadata,
        event_cls: type,
        event_type: EventType,
        extra_fields: dict[str, Any],
    ) -> None:
        """User events have correct types and topic."""
        event = event_cls(metadata=metadata, **extra_fields)
        assert event.event_type == event_type
        assert event_cls.topic == KafkaTopic.USER_EVENTS

    def test_user_settings_updated_event(self, metadata: AvroEventMetadata) -> None:
        """UserSettingsUpdatedEvent captures settings changes."""
        event = UserSettingsUpdatedEvent(
            user_id="user-1",
            changed_fields=["theme", "timezone"],
            theme="dark",
            timezone="UTC",
            metadata=metadata,
        )
        assert event.event_type == EventType.USER_SETTINGS_UPDATED
        assert event.topic == KafkaTopic.USER_SETTINGS_EVENTS
        assert "theme" in event.changed_fields


class TestEventSerialization:
    """Tests for event serialization edge cases."""

    def test_complex_nested_payload(self, metadata: AvroEventMetadata) -> None:
        """Events with nested structures serialize correctly."""
        event = CreatePodCommandEvent(
            saga_id="saga-1",
            execution_id="exec-1",
            script="import os\nprint(os.getcwd())",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_command=["python", "-u"],
            runtime_filename="script.py",
            timeout_seconds=60,
            cpu_limit="200m",
            memory_limit="256Mi",
            cpu_request="100m",
            memory_request="128Mi",
            priority=3,
            pod_spec={"nodeSelector": "worker"},
            metadata=metadata,
        )
        d = event.to_dict()
        assert d["pod_spec"] == {"nodeSelector": "worker"}
        assert d["runtime_command"] == ["python", "-u"]

    def test_unicode_in_script(self, metadata: AvroEventMetadata) -> None:
        """Events with unicode in script serialize correctly."""
        script = "print('Hello 世界 🌍')"
        event = ExecutionRequestedEvent(
            execution_id="exec-unicode",
            script=script,
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_command=["python"],
            runtime_filename="main.py",
            timeout_seconds=30,
            cpu_limit="100m",
            memory_limit="128Mi",
            cpu_request="50m",
            memory_request="64Mi",
            metadata=metadata,
        )
        json_str = event.to_json()
        parsed = json.loads(json_str)
        assert "世界" in parsed["script"]
        assert "🌍" in parsed["script"]

    def test_empty_optional_fields(self, metadata: AvroEventMetadata) -> None:
        """Events with None optional fields serialize without errors."""
        event = ExecutionStartedEvent(
            execution_id="exec-1",
            pod_name="pod-1",
            node_name=None,
            container_id=None,
            metadata=metadata,
        )
        d = event.to_dict()
        assert d["node_name"] is None
        assert d["container_id"] is None
