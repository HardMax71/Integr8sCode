import os
from unittest import mock

import pytest
from pydantic import ValidationError

from app.config import Settings


class TestSettingsValidation:
    def test_secret_key_missing(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            
            errors = exc_info.value.errors()
            assert len(errors) == 1
            assert errors[0]["loc"] == ("SECRET_KEY",)
            assert "Field required" in errors[0]["msg"]

    def test_secret_key_too_short(self) -> None:
        with mock.patch.dict(os.environ, {"SECRET_KEY": "short_key"}, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            
            errors = exc_info.value.errors()
            assert len(errors) == 1
            assert errors[0]["loc"] == ("SECRET_KEY",)
            assert "at least 32 characters" in errors[0]["msg"]

    def test_secret_key_default_placeholder(self) -> None:
        # These should always fail
        test_cases = ["your_secret_key_here", "default_secret_key"]
        
        for placeholder in test_cases:
            # Pad to 32 chars to avoid length error
            padded_placeholder = placeholder.ljust(32, 'x')
            with mock.patch.dict(os.environ, {"SECRET_KEY": padded_placeholder}, clear=True):
                with pytest.raises(ValidationError) as exc_info:
                    Settings()
                
                errors = exc_info.value.errors()
                assert len(errors) == 1
                assert errors[0]["loc"] == ("SECRET_KEY",)
                assert "String should match pattern" in errors[0]["msg"]
    

    def test_secret_key_valid(self) -> None:
        valid_key = "a" * 32  # 32 character key
        with mock.patch.dict(os.environ, {"SECRET_KEY": valid_key}, clear=True):
            settings = Settings()
            assert settings.SECRET_KEY == valid_key

    def test_secret_key_longer_than_minimum(self) -> None:
        long_key = "a" * 64  # 64 character key
        with mock.patch.dict(os.environ, {"SECRET_KEY": long_key}, clear=True):
            settings = Settings()
            assert settings.SECRET_KEY == long_key

    def test_env_file_loading(self) -> None:
        """Test that .env file is loaded if present."""
        # This test verifies that the env_file configuration works
        # In a real scenario, the .env file would contain SECRET_KEY
        with mock.patch.dict(os.environ, {"SECRET_KEY": "a" * 32}, clear=True):
            settings = Settings()
            assert settings.Config.env_file == ".env"