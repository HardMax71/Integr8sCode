import os
from unittest import mock

import pytest
from pydantic import ValidationError

from app.config import Settings


class TestSettingsValidation:
    def test_secret_key_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            
            errors = exc_info.value.errors()
            assert len(errors) == 1
            assert errors[0]["loc"] == ("SECRET_KEY",)
            assert "JWT_SECRET_KEY environment variable must be set" in errors[0]["msg"]

    def test_secret_key_too_short(self):
        with mock.patch.dict(os.environ, {"JWT_SECRET_KEY": "short_key"}, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            
            errors = exc_info.value.errors()
            assert len(errors) == 1
            assert errors[0]["loc"] == ("SECRET_KEY",)
            assert "JWT_SECRET_KEY must be at least 32 characters long" in errors[0]["msg"]

    def test_secret_key_default_placeholder(self):
        test_cases = ["your_secret_key_here", "default_secret_key"]
        
        for placeholder in test_cases:
            with mock.patch.dict(os.environ, {"JWT_SECRET_KEY": placeholder}, clear=True):
                with pytest.raises(ValidationError) as exc_info:
                    Settings()
                
                errors = exc_info.value.errors()
                assert len(errors) == 1
                assert errors[0]["loc"] == ("SECRET_KEY",)
                assert "JWT_SECRET_KEY must not use default placeholder values" in errors[0]["msg"]

    def test_secret_key_valid(self):
        valid_key = "a" * 32  # 32 character key
        with mock.patch.dict(os.environ, {"JWT_SECRET_KEY": valid_key}, clear=True):
            settings = Settings()
            assert settings.SECRET_KEY == valid_key

    def test_secret_key_longer_than_minimum(self):
        long_key = "a" * 64  # 64 character key
        with mock.patch.dict(os.environ, {"JWT_SECRET_KEY": long_key}, clear=True):
            settings = Settings()
            assert settings.SECRET_KEY == long_key