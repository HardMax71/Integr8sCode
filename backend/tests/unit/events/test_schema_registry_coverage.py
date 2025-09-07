"""Tests for app/events/schema/schema_registry.py - covering missing lines"""
import json
import struct
from datetime import datetime, timezone
from typing import Type
from unittest.mock import Mock, MagicMock, patch, PropertyMock, AsyncMock
import pytest

from confluent_kafka.schema_registry import Schema
from confluent_kafka.schema_registry.avro import AvroDeserializer, AvroSerializer
from confluent_kafka.serialization import SerializationContext, MessageField

from app.events.schema.schema_registry import (
    SchemaRegistryManager,
    _get_event_class_mapping,
    _get_all_event_classes,
    _get_event_type_to_class_mapping,
    create_schema_registry_manager,
    initialize_event_schemas,
    MAGIC_BYTE
)
from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.domain.enums.events import EventType


@pytest.fixture
def mock_settings():
    """Mock settings"""
    settings = Mock()
    settings.SCHEMA_REGISTRY_URL = "http://localhost:8081"
    settings.SCHEMA_REGISTRY_AUTH = None
    return settings


@pytest.fixture
def schema_manager(mock_settings):
    """Create SchemaRegistryManager with mocked settings"""
    with patch('app.events.schema.schema_registry.get_settings', return_value=mock_settings):
        with patch('app.events.schema.schema_registry.SchemaRegistryClient'):
            return SchemaRegistryManager()


def test_get_event_class_mapping():
    """Test _get_event_class_mapping function"""
    # Clear cache first
    _get_event_class_mapping.cache_clear()
    
    mapping = _get_event_class_mapping()
    
    # Should contain BaseEvent subclasses
    assert isinstance(mapping, dict)
    assert len(mapping) > 0
    # Check a known event class
    assert "ExecutionRequestedEvent" in mapping
    assert mapping["ExecutionRequestedEvent"] == ExecutionRequestedEvent


def test_get_all_event_classes():
    """Test _get_all_event_classes function"""
    # Clear cache first
    _get_all_event_classes.cache_clear()
    
    classes = _get_all_event_classes()
    
    assert isinstance(classes, list)
    assert len(classes) > 0
    assert ExecutionRequestedEvent in classes


def test_get_event_type_to_class_mapping():
    """Test _get_event_type_to_class_mapping function"""
    # Clear cache first
    _get_event_type_to_class_mapping.cache_clear()
    
    mapping = _get_event_type_to_class_mapping()
    
    assert isinstance(mapping, dict)
    # Should map EventType to event classes
    assert EventType.EXECUTION_REQUESTED in mapping
    assert mapping[EventType.EXECUTION_REQUESTED] == ExecutionRequestedEvent


def test_schema_registry_manager_with_auth():
    """Test SchemaRegistryManager initialization with authentication"""
    mock_settings = Mock()
    mock_settings.SCHEMA_REGISTRY_URL = "http://localhost:8081"
    mock_settings.SCHEMA_REGISTRY_AUTH = "user:pass"
    
    with patch('app.events.schema.schema_registry.get_settings', return_value=mock_settings):
        with patch('app.events.schema.schema_registry.SchemaRegistryClient') as mock_client:
            manager = SchemaRegistryManager()
            
            # Check that auth was passed to client
            mock_client.assert_called_once()
            config = mock_client.call_args[0][0]
            assert "basic.auth.user.info" in config
            assert config["basic.auth.user.info"] == "user:pass"


def test_get_event_class_by_id_from_registry(schema_manager):
    """Test _get_event_class_by_id when not in cache"""
    schema_id = 123
    
    # Mock schema from registry
    mock_schema = Mock()
    mock_schema.schema_str = json.dumps({
        "type": "record",
        "name": "ExecutionRequestedEvent",
        "fields": []
    })
    
    schema_manager.client.get_schema = Mock(return_value=mock_schema)
    
    # Clear caches
    schema_manager._id_to_class_cache = {}
    schema_manager._schema_id_cache = {}
    
    result = schema_manager._get_event_class_by_id(schema_id)
    
    assert result == ExecutionRequestedEvent
    assert schema_manager._id_to_class_cache[schema_id] == ExecutionRequestedEvent
    assert schema_manager._schema_id_cache[ExecutionRequestedEvent] == schema_id


def test_get_event_class_by_id_unknown_class(schema_manager):
    """Test _get_event_class_by_id with unknown class name"""
    schema_id = 456
    
    # Mock schema with unknown class name
    mock_schema = Mock()
    mock_schema.schema_str = json.dumps({
        "type": "record",
        "name": "UnknownEvent",
        "fields": []
    })
    
    schema_manager.client.get_schema = Mock(return_value=mock_schema)
    
    result = schema_manager._get_event_class_by_id(schema_id)
    
    assert result is None


def test_get_event_class_by_id_no_name(schema_manager):
    """Test _get_event_class_by_id when schema has no name"""
    schema_id = 789
    
    # Mock schema without name field
    mock_schema = Mock()
    mock_schema.schema_str = json.dumps({
        "type": "record",
        "fields": []
    })
    
    schema_manager.client.get_schema = Mock(return_value=mock_schema)
    
    result = schema_manager._get_event_class_by_id(schema_id)
    
    assert result is None


def test_serialize_event_creates_serializer(schema_manager):
    """Test serialize_event creates and caches serializer"""
    event = ExecutionRequestedEvent(
        execution_id="test_123",
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
        metadata={
            "service_name": "test-service",
            "service_version": "1.0.0"
        }
    )
    
    # Mock the schema registration
    schema_manager._get_schema_id = Mock(return_value=100)
    
    # Mock AvroSerializer
    mock_serializer = Mock()
    mock_serializer.return_value = b"serialized_data"
    
    with patch('app.events.schema.schema_registry.AvroSerializer', return_value=mock_serializer):
        result = schema_manager.serialize_event(event)
    
    assert result == b"serialized_data"
    assert "ExecutionRequestedEvent-value" in schema_manager._serializers


def test_serialize_event_with_timestamp(schema_manager):
    """Test serialize_event converts timestamp to microseconds"""
    # Create a mock event with timestamp
    event = Mock(spec=BaseEvent)
    event.__class__ = ExecutionRequestedEvent
    event.topic = "test-topic"
    timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    event.model_dump = Mock(return_value={
        "execution_id": "test",
        "timestamp": timestamp,
        "event_type": "execution_requested"
    })
    
    # Mock schema and serializer
    schema_manager._get_schema_id = Mock(return_value=100)
    mock_serializer = Mock(return_value=b"serialized")
    schema_manager._serializers["ExecutionRequestedEvent-value"] = mock_serializer
    
    result = schema_manager.serialize_event(event)
    
    # Check that timestamp was converted to microseconds
    call_args = mock_serializer.call_args[0][0]
    assert "timestamp" in call_args
    assert call_args["timestamp"] == int(timestamp.timestamp() * 1_000_000)


def test_serialize_event_returns_none_raises(schema_manager):
    """Test serialize_event raises when serializer returns None"""
    event = ExecutionRequestedEvent(
        execution_id="test_123",
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
        metadata={
            "service_name": "test-service",
            "service_version": "1.0.0"
        }
    )
    
    schema_manager._get_schema_id = Mock(return_value=100)
    
    # Mock serializer to return None
    mock_serializer = Mock(return_value=None)
    schema_manager._serializers["ExecutionRequestedEvent-value"] = mock_serializer
    
    with pytest.raises(ValueError, match="Serialization returned None"):
        schema_manager.serialize_event(event)


def test_deserialize_event_too_short(schema_manager):
    """Test deserialize_event with data too short for wire format"""
    with pytest.raises(ValueError, match="Invalid message: too short"):
        schema_manager.deserialize_event(b"abc", "test-topic")


def test_deserialize_event_wrong_magic_byte(schema_manager):
    """Test deserialize_event with wrong magic byte"""
    data = b"\x99" + struct.pack(">I", 123) + b"payload"
    
    with pytest.raises(ValueError, match="Unknown magic byte"):
        schema_manager.deserialize_event(data, "test-topic")


def test_deserialize_event_unknown_schema_id(schema_manager):
    """Test deserialize_event with unknown schema ID"""
    schema_id = 999
    data = MAGIC_BYTE + struct.pack(">I", schema_id) + b"payload"
    
    schema_manager._get_event_class_by_id = Mock(return_value=None)
    
    with pytest.raises(ValueError, match="Unknown schema ID"):
        schema_manager.deserialize_event(data, "test-topic")


def test_deserialize_event_creates_deserializer(schema_manager):
    """Test deserialize_event creates deserializer when None"""
    schema_id = 100
    data = MAGIC_BYTE + struct.pack(">I", schema_id) + b"payload"
    
    # Setup mocks
    schema_manager._get_event_class_by_id = Mock(return_value=ExecutionRequestedEvent)
    
    mock_deserializer = Mock(return_value={
        "execution_id": "test",
        "script": "print('hello')",
        "language": "python",
        "language_version": "3.11",
        "event_type": "execution_requested",
        "runtime_image": "python:3.11-slim",
        "runtime_command": ["python"],
        "runtime_filename": "main.py",
        "timeout_seconds": 30,
        "cpu_limit": "100m",
        "memory_limit": "128Mi",
        "cpu_request": "50m",
        "memory_request": "64Mi",
        "metadata": {
            "service_name": "test-service",
            "service_version": "1.0.0"
        }
    })
    
    with patch('app.events.schema.schema_registry.AvroDeserializer', return_value=mock_deserializer):
        result = schema_manager.deserialize_event(data, "test-topic")
    
    assert schema_manager._deserializer is not None
    assert isinstance(result, ExecutionRequestedEvent)


def test_deserialize_event_non_dict_result(schema_manager):
    """Test deserialize_event when deserializer returns non-dict"""
    schema_id = 100
    data = MAGIC_BYTE + struct.pack(">I", schema_id) + b"payload"
    
    schema_manager._get_event_class_by_id = Mock(return_value=ExecutionRequestedEvent)
    
    # Mock deserializer to return non-dict
    mock_deserializer = Mock(return_value="not_a_dict")
    schema_manager._deserializer = mock_deserializer
    
    with pytest.raises(ValueError, match="expected dict"):
        schema_manager.deserialize_event(data, "test-topic")


def test_deserialize_event_restores_event_type(schema_manager):
    """Test deserialize_event restores event_type from model field default"""
    schema_id = 100
    data = MAGIC_BYTE + struct.pack(">I", schema_id) + b"payload"
    
    schema_manager._get_event_class_by_id = Mock(return_value=ExecutionRequestedEvent)
    
    # Mock deserializer to return dict without event_type
    mock_deserializer = Mock(return_value={
        "execution_id": "test",
        "script": "print('hello')",
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
        "metadata": {
            "service_name": "test-service",
            "service_version": "1.0.0"
        }
        # Note: no event_type field
    })
    schema_manager._deserializer = mock_deserializer
    
    result = schema_manager.deserialize_event(data, "test-topic")
    
    # Check that event_type was restored from the model field default
    assert result.event_type == EventType.EXECUTION_REQUESTED


def test_deserialize_json_unknown_event_type(schema_manager):
    """Test deserialize_json with unknown event type"""
    # Create a mock unknown event type
    data = {
        "event_type": "unknown_event_type"
    }
    
    with pytest.raises(ValueError, match="is not a valid EventType"):
        schema_manager.deserialize_json(data)


def test_set_compatibility_invalid_mode(schema_manager):
    """Test set_compatibility with invalid mode"""
    with pytest.raises(ValueError, match="Invalid compatibility mode"):
        schema_manager.set_compatibility("test-subject", "INVALID_MODE")


def test_set_compatibility_valid_mode(schema_manager):
    """Test set_compatibility with valid mode"""
    with patch('app.events.schema.schema_registry.httpx.put') as mock_put:
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_put.return_value = mock_response
        
        schema_manager.set_compatibility("test-subject", "FORWARD")
        
        mock_put.assert_called_once_with(
            "http://localhost:8081/config/test-subject",
            json={"compatibility": "FORWARD"}
        )


@pytest.mark.asyncio
async def test_initialize_schemas(schema_manager):
    """Test initialize_schemas method"""
    # Mock methods
    schema_manager.set_compatibility = Mock()
    schema_manager.register_schema = Mock(return_value=100)
    
    # Clear the initialized flag
    schema_manager._initialized = False
    
    await schema_manager.initialize_schemas()
    
    # Should register all event classes
    event_classes = _get_all_event_classes()
    assert schema_manager.set_compatibility.call_count == len(event_classes)
    assert schema_manager.register_schema.call_count == len(event_classes)
    assert schema_manager._initialized is True
    
    # Should not re-initialize if already initialized
    schema_manager.set_compatibility.reset_mock()
    schema_manager.register_schema.reset_mock()
    
    await schema_manager.initialize_schemas()
    
    schema_manager.set_compatibility.assert_not_called()
    schema_manager.register_schema.assert_not_called()


def test_create_schema_registry_manager():
    """Test create_schema_registry_manager factory function"""
    with patch('app.events.schema.schema_registry.get_settings') as mock_settings:
        mock_settings.return_value.SCHEMA_REGISTRY_URL = "http://test:8081"
        mock_settings.return_value.SCHEMA_REGISTRY_AUTH = None
        
        with patch('app.events.schema.schema_registry.SchemaRegistryClient'):
            manager = create_schema_registry_manager("http://custom:8082")
            
            assert isinstance(manager, SchemaRegistryManager)
            assert manager.url == "http://custom:8082"


@pytest.mark.asyncio
async def test_initialize_event_schemas():
    """Test initialize_event_schemas function"""
    mock_registry = Mock(spec=SchemaRegistryManager)
    mock_registry.initialize_schemas = AsyncMock()
    
    await initialize_event_schemas(mock_registry)
    
    mock_registry.initialize_schemas.assert_called_once()


def test_serialize_event_without_timestamp(schema_manager):
    """Test serialize_event when event has no timestamp"""
    event = Mock(spec=BaseEvent)
    event.__class__ = ExecutionRequestedEvent
    event.topic = "test-topic"
    event.model_dump = Mock(return_value={
        "execution_id": "test",
        "event_type": "execution_requested"
    })
    
    schema_manager._get_schema_id = Mock(return_value=100)
    mock_serializer = Mock(return_value=b"serialized")
    schema_manager._serializers["ExecutionRequestedEvent-value"] = mock_serializer
    
    result = schema_manager.serialize_event(event)
    
    # Should not raise and should serialize successfully
    assert result == b"serialized"
    call_args = mock_serializer.call_args[0][0]
    assert "timestamp" not in call_args


def test_serialize_event_with_null_timestamp(schema_manager):
    """Test serialize_event when timestamp is None"""
    event = Mock(spec=BaseEvent)
    event.__class__ = ExecutionRequestedEvent
    event.topic = "test-topic"
    event.model_dump = Mock(return_value={
        "execution_id": "test",
        "timestamp": None,
        "event_type": "execution_requested"
    })
    
    schema_manager._get_schema_id = Mock(return_value=100)
    mock_serializer = Mock(return_value=b"serialized")
    schema_manager._serializers["ExecutionRequestedEvent-value"] = mock_serializer
    
    result = schema_manager.serialize_event(event)
    
    assert result == b"serialized"
    call_args = mock_serializer.call_args[0][0]
    assert call_args["timestamp"] is None  # Should remain None, not converted