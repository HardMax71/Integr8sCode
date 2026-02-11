import pytest
from pydantic import ValidationError

from app.domain.admin import SystemSettings

pytestmark = pytest.mark.unit


class TestDefaults:
    def test_defaults(self) -> None:
        s = SystemSettings()
        assert s.max_timeout_seconds == 300
        assert s.memory_limit == "512Mi"
        assert s.cpu_limit == "2000m"
        assert s.max_concurrent_executions == 10
        assert s.password_min_length == 8
        assert s.session_timeout_minutes == 60
        assert s.max_login_attempts == 5
        assert s.lockout_duration_minutes == 15
        assert s.metrics_retention_days == 30
        assert s.log_level == "INFO"
        assert s.enable_tracing is True
        assert s.sampling_rate == 0.1


class TestK8sPatternValidation:
    @pytest.mark.parametrize("value", ["512Mi", "1Gi", "256Ki", "1024Mi"])
    def test_valid_memory_limit(self, value: str) -> None:
        s = SystemSettings(memory_limit=value)
        assert s.memory_limit == value

    @pytest.mark.parametrize("value", ["512mb", "1G", "abc", "512", "Mi512"])
    def test_invalid_memory_limit(self, value: str) -> None:
        with pytest.raises(ValidationError, match="memory_limit"):
            SystemSettings(memory_limit=value)

    @pytest.mark.parametrize("value", ["1000m", "500m", "2000m"])
    def test_valid_cpu_limit(self, value: str) -> None:
        s = SystemSettings(cpu_limit=value)
        assert s.cpu_limit == value

    @pytest.mark.parametrize("value", ["1000", "2 cores", "500mc", "m500"])
    def test_invalid_cpu_limit(self, value: str) -> None:
        with pytest.raises(ValidationError, match="cpu_limit"):
            SystemSettings(cpu_limit=value)


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
            ("metrics_retention_days", 6, 91),
        ],
    )
    def test_rejects_out_of_range(self, field: str, too_low: int, too_high: int) -> None:
        with pytest.raises(ValidationError):
            SystemSettings.model_validate({field: too_low})
        with pytest.raises(ValidationError):
            SystemSettings.model_validate({field: too_high})

    def test_sampling_rate_boundaries(self) -> None:
        assert SystemSettings(sampling_rate=0.0).sampling_rate == 0.0
        assert SystemSettings(sampling_rate=1.0).sampling_rate == 1.0
        with pytest.raises(ValidationError):
            SystemSettings(sampling_rate=-0.1)
        with pytest.raises(ValidationError):
            SystemSettings(sampling_rate=1.1)


class TestLogLevel:
    @pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    def test_valid_log_levels(self, level: str) -> None:
        s = SystemSettings.model_validate({"log_level": level})
        assert s.log_level == level

    def test_invalid_log_level(self) -> None:
        with pytest.raises(ValidationError):
            SystemSettings(log_level="TRACE")  # type: ignore[arg-type]


class TestExtraFieldsIgnored:
    def test_extra_fields_ignored(self) -> None:
        s = SystemSettings.model_validate({"max_timeout_seconds": 100, "unknown_field": "whatever"})
        assert s.max_timeout_seconds == 100
        assert not hasattr(s, "unknown_field")
