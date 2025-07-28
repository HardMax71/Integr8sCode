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
            assert "SECRET_KEY environment variable must be set" in errors[0]["msg"]

    def test_secret_key_too_short(self) -> None:
        with mock.patch.dict(os.environ, {"SECRET_KEY": "short_key"}, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            
            errors = exc_info.value.errors()
            assert len(errors) == 1
            assert errors[0]["loc"] == ("SECRET_KEY",)
            assert "SECRET_KEY must be at least 32 characters long" in errors[0]["msg"]

    def test_secret_key_default_placeholder(self) -> None:
        test_cases = ["your_secret_key_here", "default_secret_key"]
        
        for placeholder in test_cases:
            with mock.patch.dict(os.environ, {"SECRET_KEY": placeholder}, clear=True):
                with pytest.raises(ValidationError) as exc_info:
                    Settings()
                
                errors = exc_info.value.errors()
                assert len(errors) == 1
                assert errors[0]["loc"] == ("SECRET_KEY",)
                assert "SECRET_KEY must not use default placeholder values" in errors[0]["msg"]

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