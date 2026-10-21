import pytest
from pydantic import ValidationError

from app.schemas_pydantic.admin_settings import SystemSettingsSchema

pytestmark = pytest.mark.unit


class TestK8sPatternValidation:
    @pytest.mark.parametrize("value", ["512Mi", "1Gi", "256Ki", "1024Mi"])
    def test_valid_memory_limit(self, value: str) -> None:
        s = SystemSettingsSchema(memory_limit=value)
        assert s.memory_limit == value

    @pytest.mark.parametrize("value", ["512mb", "1G", "abc", "512", "Mi512", "0Mi"])
    def test_invalid_memory_limit(self, value: str) -> None:
        with pytest.raises(ValidationError, match="memory_limit"):
            SystemSettingsSchema(memory_limit=value)

    @pytest.mark.parametrize("value", ["1000m", "500m", "2000m"])
    def test_valid_cpu_limit(self, value: str) -> None:
        s = SystemSettingsSchema(cpu_limit=value)
        assert s.cpu_limit == value

    @pytest.mark.parametrize("value", ["1000", "2 cores", "500mc", "m500", "0m"])
    def test_invalid_cpu_limit(self, value: str) -> None:
        with pytest.raises(ValidationError, match="cpu_limit"):
            SystemSettingsSchema(cpu_limit=value)


class TestBoundaryValidation:
    @pytest.mark.parametrize(
        "field, too_low, too_high",
        [
            ("max_timeout_seconds", 0, 3601),
            ("max_concurrent_executions", 0, 101),
            ("password_min_length", 7, 33),
            ("session_timeout_minutes", 4, 1441),
            ("max_login_attempts", 2, 11),
            ("lockout_duration_minutes", 4, 61),
        ],
    )
    def test_rejects_out_of_range(self, field: str, too_low: int, too_high: int) -> None:
        with pytest.raises(ValidationError):
            SystemSettingsSchema.model_validate({field: too_low})
        with pytest.raises(ValidationError):
            SystemSettingsSchema.model_validate({field: too_high})


class TestExtraFieldsIgnored:
    def test_extra_fields_ignored(self) -> None:
        s = SystemSettingsSchema.model_validate({"max_timeout_seconds": 100, "unknown_field": "whatever"})
        assert s.max_timeout_seconds == 100
        assert not hasattr(s, "unknown_field")
