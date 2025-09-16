"""Tests for saved script mapper to achieve 95%+ coverage."""

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID

import pytest

from app.domain.saved_script.models import (
    DomainSavedScript,
    DomainSavedScriptCreate,
    DomainSavedScriptUpdate,
)
from app.infrastructure.mappers.saved_script_mapper import SavedScriptMapper


@pytest.fixture
def sample_create_script():
    """Create a sample script creation object with all fields."""
    return DomainSavedScriptCreate(
        name="Test Script",
        script="print('Hello, World!')",
        lang="python",
        lang_version="3.11",
        description="A test script for unit testing",
    )


@pytest.fixture
def sample_create_script_minimal():
    """Create a minimal script creation object."""
    return DomainSavedScriptCreate(
        name="Minimal Script",
        script="console.log('test')",
    )


@pytest.fixture
def sample_update_all_fields():
    """Create an update object with all fields."""
    return DomainSavedScriptUpdate(
        name="Updated Name",
        script="print('Updated')",
        lang="python",
        lang_version="3.12",
        description="Updated description",
    )


@pytest.fixture
def sample_update_partial():
    """Create an update object with only some fields."""
    return DomainSavedScriptUpdate(
        name="New Name",
        script=None,
        lang=None,
        lang_version=None,
        description="New description",
    )


@pytest.fixture
def sample_mongo_document():
    """Create a sample MongoDB document with all fields."""
    return {
        "_id": "mongo_id_123",
        "script_id": "script-123",
        "user_id": "user-456",
        "name": "DB Script",
        "script": "def main(): pass",
        "lang": "python",
        "lang_version": "3.10",
        "description": "Script from database",
        "created_at": datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
        "extra_field": "should be ignored",
    }


class TestSavedScriptMapper:
    """Test SavedScriptMapper methods."""

    def test_to_insert_document_with_all_fields(self, sample_create_script):
        """Test creating insert document with all fields."""
        user_id = "test-user-123"

        with patch('app.infrastructure.mappers.saved_script_mapper.uuid4') as mock_uuid:
            mock_uuid.return_value = UUID('12345678-1234-5678-1234-567812345678')

            doc = SavedScriptMapper.to_insert_document(sample_create_script, user_id)

        assert doc["script_id"] == "12345678-1234-5678-1234-567812345678"
        assert doc["user_id"] == user_id
        assert doc["name"] == "Test Script"
        assert doc["script"] == "print('Hello, World!')"
        assert doc["lang"] == "python"
        assert doc["lang_version"] == "3.11"
        assert doc["description"] == "A test script for unit testing"
        assert isinstance(doc["created_at"], datetime)
        assert isinstance(doc["updated_at"], datetime)
        assert doc["created_at"] == doc["updated_at"]  # Should be same timestamp

    def test_to_insert_document_with_minimal_fields(self, sample_create_script_minimal):
        """Test creating insert document with minimal fields (using defaults)."""
        user_id = "minimal-user"

        doc = SavedScriptMapper.to_insert_document(sample_create_script_minimal, user_id)

        assert doc["user_id"] == user_id
        assert doc["name"] == "Minimal Script"
        assert doc["script"] == "console.log('test')"
        assert doc["lang"] == "python"  # Default value
        assert doc["lang_version"] == "3.11"  # Default value
        assert doc["description"] is None  # Optional field
        assert "script_id" in doc
        assert "created_at" in doc
        assert "updated_at" in doc

    def test_to_update_dict_with_all_fields(self, sample_update_all_fields):
        """Test converting update object with all fields to dict."""
        update_dict = SavedScriptMapper.to_update_dict(sample_update_all_fields)

        assert update_dict["name"] == "Updated Name"
        assert update_dict["script"] == "print('Updated')"
        assert update_dict["lang"] == "python"
        assert update_dict["lang_version"] == "3.12"
        assert update_dict["description"] == "Updated description"
        assert "updated_at" in update_dict
        assert isinstance(update_dict["updated_at"], datetime)

    def test_to_update_dict_with_none_fields(self, sample_update_partial):
        """Test that None fields are filtered out from update dict."""
        update_dict = SavedScriptMapper.to_update_dict(sample_update_partial)

        assert update_dict["name"] == "New Name"
        assert "script" not in update_dict  # None value should be filtered
        assert "lang" not in update_dict  # None value should be filtered
        assert "lang_version" not in update_dict  # None value should be filtered
        assert update_dict["description"] == "New description"
        assert "updated_at" in update_dict

    def test_to_update_dict_with_only_updated_at(self):
        """Test update with all fields None except updated_at."""
        update = DomainSavedScriptUpdate()  # All fields default to None

        update_dict = SavedScriptMapper.to_update_dict(update)

        # Only updated_at should be present (it has a default factory)
        assert len(update_dict) == 1
        assert "updated_at" in update_dict
        assert isinstance(update_dict["updated_at"], datetime)

    def test_from_mongo_document_with_all_fields(self, sample_mongo_document):
        """Test converting MongoDB document to domain model with all fields."""
        script = SavedScriptMapper.from_mongo_document(sample_mongo_document)

        assert script.script_id == "script-123"
        assert script.user_id == "user-456"
        assert script.name == "DB Script"
        assert script.script == "def main(): pass"
        assert script.lang == "python"
        assert script.lang_version == "3.10"
        assert script.description == "Script from database"
        assert script.created_at == datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        assert script.updated_at == datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
        # Extra field should be ignored
        assert not hasattr(script, "extra_field")
        assert not hasattr(script, "_id")

    def test_from_mongo_document_with_missing_optional_fields(self):
        """Test converting MongoDB document with missing optional fields."""
        doc = {
            "script_id": "minimal-123",
            "user_id": "minimal-user",
            "name": "Minimal",
            "script": "pass",
            "lang": "python",
            "lang_version": "3.9",
            # No description, created_at, or updated_at
        }

        script = SavedScriptMapper.from_mongo_document(doc)

        assert script.script_id == "minimal-123"
        assert script.user_id == "minimal-user"
        assert script.name == "Minimal"
        assert script.script == "pass"
        assert script.lang == "python"
        assert script.lang_version == "3.9"
        assert script.description is None  # Should use dataclass default
        # created_at and updated_at should use dataclass defaults
        assert isinstance(script.created_at, datetime)
        assert isinstance(script.updated_at, datetime)

    def test_from_mongo_document_with_non_string_fields(self):
        """Test type coercion when fields are not strings."""
        doc = {
            "script_id": 123,  # Integer instead of string
            "user_id": 456,  # Integer instead of string
            "name": 789,  # Integer instead of string
            "script": {"code": "test"},  # Dict instead of string
            "lang": ["python"],  # List instead of string
            "lang_version": 3.11,  # Float instead of string
            "description": "Valid description",
            "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "updated_at": datetime(2024, 1, 2, tzinfo=timezone.utc),
        }

        script = SavedScriptMapper.from_mongo_document(doc)

        # All fields should be coerced to strings
        assert script.script_id == "123"
        assert script.user_id == "456"
        assert script.name == "789"
        assert script.script == "{'code': 'test'}"
        assert script.lang == "['python']"
        assert script.lang_version == "3.11"
        assert script.description == "Valid description"

    def test_from_mongo_document_empty(self):
        """Test converting empty MongoDB document should fail."""
        doc = {}

        # Should raise TypeError since required fields are missing
        with pytest.raises(TypeError) as exc_info:
            SavedScriptMapper.from_mongo_document(doc)

        assert "missing" in str(exc_info.value).lower()

    def test_from_mongo_document_only_unknown_fields(self):
        """Test converting document with only unknown fields should fail."""
        doc = {
            "_id": "some_id",
            "unknown_field1": "value1",
            "unknown_field2": "value2",
            "not_in_dataclass": "value3",
        }

        # Should raise TypeError since required fields are missing
        with pytest.raises(TypeError) as exc_info:
            SavedScriptMapper.from_mongo_document(doc)

        assert "missing" in str(exc_info.value).lower()

    def test_from_mongo_document_partial_string_fields(self):
        """Test with some string fields present and some missing should fail."""
        doc = {
            "script_id": "id-123",
            "user_id": 999,  # Non-string, should be coerced
            "name": "Test",
            # script is missing - required field
            "lang": "javascript",
            # lang_version is missing
            "description": None,  # Explicitly None
        }

        # Should raise TypeError since required field 'script' is missing
        with pytest.raises(TypeError) as exc_info:
            SavedScriptMapper.from_mongo_document(doc)

        assert "missing" in str(exc_info.value).lower()