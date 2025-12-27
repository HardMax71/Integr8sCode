"""Extended tests for saga mapper to achieve 95%+ coverage."""

from datetime import datetime, timezone
from typing import Any

import pytest

from app.domain.enums.saga import SagaState
from app.domain.saga.models import Saga, SagaFilter, SagaInstance
from app.infrastructure.mappers.saga_mapper import (
    SagaEventMapper,
    SagaFilterMapper,
    SagaInstanceMapper,
    SagaMapper,
)


@pytest.fixture
def sample_saga():
    """Create a sample saga with all fields."""
    return Saga(
        saga_id="saga-123",
        saga_name="test-saga",
        execution_id="exec-456",
        state=SagaState.RUNNING,
        current_step="step-2",
        completed_steps=["step-1"],
        compensated_steps=[],
        context_data={"key": "value", "_private": "secret", "user_id": "user-789"},
        error_message="Some error",
        created_at=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc),
        completed_at=datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
        retry_count=2,
    )


@pytest.fixture
def sample_saga_instance():
    """Create a sample saga instance."""
    return SagaInstance(
        saga_id="inst-123",
        saga_name="test-instance",
        execution_id="exec-789",
        state=SagaState.COMPENSATING,
        current_step="compensate-1",
        completed_steps=["step-1", "step-2"],
        compensated_steps=["step-2"],
        context_data={"data": "test", "_internal": "hidden"},
        error_message="Failed step",
        created_at=datetime(2024, 1, 2, 9, 0, 0, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 2, 9, 30, 0, tzinfo=timezone.utc),
        completed_at=None,
        retry_count=1,
    )


class TestSagaMapper:
    """Extended tests for SagaMapper."""

    def test_to_mongo_with_private_keys(self, sample_saga):
        """Test that private keys (starting with '_') are filtered out."""
        mapper = SagaMapper()
        doc = mapper.to_mongo(sample_saga)

        # Private key should be filtered out
        assert "_private" not in doc["context_data"]
        assert "key" in doc["context_data"]
        assert "user_id" in doc["context_data"]

    def test_to_mongo_with_none_context(self):
        """Test handling of None context_data."""
        saga = Saga(
            saga_id="saga-001",
            saga_name="test",
            execution_id="exec-001",
            state=SagaState.CREATED,
            context_data=None,
        )

        mapper = SagaMapper()
        doc = mapper.to_mongo(saga)

        assert doc["context_data"] == {}

    def test_to_mongo_with_non_dict_context(self):
        """Test handling of non-dict context_data."""
        saga = Saga(
            saga_id="saga-002",
            saga_name="test",
            execution_id="exec-002",
            state=SagaState.CREATED,
            context_data="not a dict",  # Invalid but testing defensive code
        )

        mapper = SagaMapper()
        doc = mapper.to_mongo(saga)

        # Should return the non-dict value as-is (line 38 checks isinstance)
        assert doc["context_data"] == "not a dict"

    def test_from_instance(self, sample_saga_instance):
        """Test converting SagaInstance to Saga."""
        mapper = SagaMapper()
        saga = mapper.from_instance(sample_saga_instance)

        assert saga.saga_id == sample_saga_instance.saga_id
        assert saga.saga_name == sample_saga_instance.saga_name
        assert saga.execution_id == sample_saga_instance.execution_id
        assert saga.state == sample_saga_instance.state
        assert saga.current_step == sample_saga_instance.current_step
        assert saga.completed_steps == sample_saga_instance.completed_steps
        assert saga.compensated_steps == sample_saga_instance.compensated_steps
        assert saga.context_data == sample_saga_instance.context_data
        assert saga.error_message == sample_saga_instance.error_message
        assert saga.retry_count == sample_saga_instance.retry_count


class TestSagaInstanceMapper:
    """Extended tests for SagaInstanceMapper."""

    def test_from_mongo_with_invalid_state(self):
        """Test from_mongo with invalid state value that triggers exception."""
        doc = {
            "saga_id": "saga-123",
            "saga_name": "test",
            "execution_id": "exec-123",
            "state": 12345,  # Invalid state (not string or SagaState)
            "completed_steps": [],
            "compensated_steps": [],
            "context_data": {},
            "retry_count": 0,
        }

        instance = SagaInstanceMapper.from_mongo(doc)

        # Should fall back to CREATED on exception (line 127)
        assert instance.state == SagaState.CREATED

    def test_from_mongo_with_saga_state_enum(self):
        """Test from_mongo when state is already a SagaState enum."""
        doc = {
            "saga_id": "saga-124",
            "saga_name": "test",
            "execution_id": "exec-124",
            "state": SagaState.COMPLETED,  # Already an enum
            "completed_steps": ["step-1"],
            "compensated_steps": [],
            "context_data": {},
            "retry_count": 1,
        }

        instance = SagaInstanceMapper.from_mongo(doc)

        assert instance.state == SagaState.COMPLETED

    def test_from_mongo_without_datetime_fields(self):
        """Test from_mongo without created_at and updated_at."""
        doc = {
            "saga_id": "saga-125",
            "saga_name": "test",
            "execution_id": "exec-125",
            "state": "running",
            "completed_steps": [],
            "compensated_steps": [],
            "context_data": {},
            "retry_count": 0,
            # No created_at or updated_at
        }

        instance = SagaInstanceMapper.from_mongo(doc)

        assert instance.saga_id == "saga-125"
        # Should have default datetime values
        assert instance.created_at is not None
        assert instance.updated_at is not None

    def test_from_mongo_with_datetime_fields(self):
        """Test from_mongo with created_at and updated_at present."""
        now = datetime.now(timezone.utc)
        doc = {
            "saga_id": "saga-126",
            "saga_name": "test",
            "execution_id": "exec-126",
            "state": "running",
            "completed_steps": [],
            "compensated_steps": [],
            "context_data": {},
            "retry_count": 0,
            "created_at": now,
            "updated_at": now,
        }

        instance = SagaInstanceMapper.from_mongo(doc)

        assert instance.created_at == now
        assert instance.updated_at == now

    def test_to_mongo_with_various_context_types(self):
        """Test to_mongo with different value types in context_data."""

        class CustomObject:
            def __str__(self):
                return "custom_str"

        class BadObject:
            def __str__(self):
                raise ValueError("Cannot convert")

        instance = SagaInstance(
            saga_name="test",
            execution_id="exec-127",
            context_data={
                "_private": "should be skipped",
                "string": "test",
                "int": 42,
                "float": 3.14,
                "bool": True,
                "list": [1, 2, 3],
                "dict": {"nested": "value"},
                "none": None,
                "custom": CustomObject(),
                "bad": BadObject(),
            }
        )

        doc = SagaInstanceMapper.to_mongo(instance)

        # Check filtered context
        context = doc["context_data"]
        assert "_private" not in context
        assert context["string"] == "test"
        assert context["int"] == 42
        assert context["float"] == 3.14
        assert context["bool"] is True
        assert context["list"] == [1, 2, 3]
        assert context["dict"] == {"nested": "value"}
        assert context["none"] is None
        assert context["custom"] == "custom_str"  # Converted to string
        assert "bad" not in context  # Skipped due to exception

    def test_to_mongo_with_state_without_value_attr(self):
        """Test to_mongo when state doesn't have 'value' attribute."""
        instance = SagaInstance(
            saga_name="test",
            execution_id="exec-128",
        )
        # Mock the state to not have 'value' attribute
        instance.state = "MOCK_STATE"  # String instead of enum

        doc = SagaInstanceMapper.to_mongo(instance)

        # Should use str(state) fallback (line 171)
        assert doc["state"] == "MOCK_STATE"


class TestSagaEventMapper:
    """Extended tests for SagaEventMapper."""

    def test_to_cancelled_event_with_user_id_param(self, sample_saga_instance):
        """Test cancelled event with user_id parameter."""
        event = SagaEventMapper.to_cancelled_event(
            sample_saga_instance,
            user_id="param-user",
            service_name="test-service",
            service_version="2.0.0",
        )

        assert event.cancelled_by == "param-user"
        assert event.metadata.user_id == "param-user"
        assert event.metadata.service_name == "test-service"
        assert event.metadata.service_version == "2.0.0"

    def test_to_cancelled_event_from_context(self):
        """Test cancelled event taking user_id from context_data."""
        instance = SagaInstance(
            saga_name="test",
            execution_id="exec-129",
            context_data={"user_id": "context-user"},
            error_message="Context error",
        )

        event = SagaEventMapper.to_cancelled_event(instance)

        assert event.cancelled_by == "context-user"
        assert event.reason == "Context error"

    def test_to_cancelled_event_default_system(self):
        """Test cancelled event defaulting to 'system' when no user_id."""
        instance = SagaInstance(
            saga_name="test",
            execution_id="exec-130",
            context_data={},  # No user_id
            error_message=None,  # No error message
        )

        event = SagaEventMapper.to_cancelled_event(instance)

        assert event.cancelled_by == "system"
        assert event.reason == "User requested cancellation"  # Default reason


class TestSagaFilterMapper:
    """Extended tests for SagaFilterMapper."""

    def test_to_mongodb_query_with_error_status_true(self):
        """Test filter with error_status=True (has errors)."""
        filter_obj = SagaFilter(
            error_status=True  # Looking for sagas with errors
        )

        mapper = SagaFilterMapper()
        query = mapper.to_mongodb_query(filter_obj)

        assert query["error_message"] == {"$ne": None}

    def test_to_mongodb_query_with_error_status_false(self):
        """Test filter with error_status=False (no errors)."""
        filter_obj = SagaFilter(
            error_status=False  # Looking for sagas without errors
        )

        mapper = SagaFilterMapper()
        query = mapper.to_mongodb_query(filter_obj)

        assert query["error_message"] is None

    def test_to_mongodb_query_with_created_after_only(self):
        """Test filter with only created_after."""
        after_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        filter_obj = SagaFilter(
            created_after=after_date
        )

        mapper = SagaFilterMapper()
        query = mapper.to_mongodb_query(filter_obj)

        assert query["created_at"] == {"$gte": after_date}

    def test_to_mongodb_query_with_created_before_only(self):
        """Test filter with only created_before."""
        before_date = datetime(2024, 12, 31, tzinfo=timezone.utc)
        filter_obj = SagaFilter(
            created_before=before_date
        )

        mapper = SagaFilterMapper()
        query = mapper.to_mongodb_query(filter_obj)

        assert query["created_at"] == {"$lte": before_date}

    def test_to_mongodb_query_with_both_dates(self):
        """Test filter with both created_after and created_before."""
        after_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        before_date = datetime(2024, 12, 31, tzinfo=timezone.utc)
        filter_obj = SagaFilter(
            created_after=after_date,
            created_before=before_date
        )

        mapper = SagaFilterMapper()
        query = mapper.to_mongodb_query(filter_obj)

        assert query["created_at"] == {
            "$gte": after_date,
            "$lte": before_date
        }

    def test_to_mongodb_query_empty_filter(self):
        """Test empty filter produces empty query."""
        filter_obj = SagaFilter()

        mapper = SagaFilterMapper()
        query = mapper.to_mongodb_query(filter_obj)

        assert query == {}