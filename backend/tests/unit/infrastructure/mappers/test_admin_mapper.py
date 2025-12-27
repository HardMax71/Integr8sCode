import pytest
from datetime import datetime, timezone

from app.infrastructure.mappers import AuditLogMapper, SettingsMapper, UserMapper
from app.domain.admin import (
    AuditAction,
    AuditLogEntry,
    ExecutionLimits,
    MonitoringSettings,
    SecuritySettings,
    SystemSettings,
)
from app.domain.user import User as DomainAdminUser
from app.domain.user import UserRole, UserUpdate, UserCreation
from app.schemas_pydantic.user import User as ServiceUser


pytestmark = pytest.mark.unit


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_user_mapper_roundtrip_and_validation() -> None:
    user = DomainAdminUser(
        user_id="u1",
        username="alice",
        email="alice@example.com",
        role=UserRole.USER,
        is_active=True,
        is_superuser=False,
        hashed_password="h",
        created_at=_now(),
        updated_at=_now(),
    )

    doc = UserMapper.to_mongo_document(user)
    back = UserMapper.from_mongo_document(doc)
    assert back.user_id == user.user_id and back.email == user.email

    # invalid email
    doc_bad = {**doc, "email": "bad"}
    with pytest.raises(ValueError):
        UserMapper.from_mongo_document(doc_bad)

    # missing required field
    bad2 = doc.copy(); bad2.pop("username")
    with pytest.raises(ValueError):
        UserMapper.from_mongo_document(bad2)


def test_user_mapper_from_service_and_update_dict() -> None:
    service_user = ServiceUser(
        user_id="u2",
        username="bob",
        email="bob@example.com",
        role=UserRole.ADMIN,
        is_active=True,
        is_superuser=True,
    )
    domain_user = UserMapper.from_pydantic_service_user(service_user)
    assert domain_user.user_id == "u2" and domain_user.is_superuser is True

    upd = UserUpdate(username="new", email="new@example.com", role=UserRole.USER, is_active=False)
    upd_dict = UserMapper.to_update_dict(upd)
    assert upd_dict["username"] == "new" and upd_dict["role"] == UserRole.USER.value

    with pytest.raises(ValueError):
        UserMapper.to_update_dict(UserUpdate(email="bad"))

    creation = UserCreation(username="c", email="c@example.com", password="12345678")
    cdict = UserMapper.user_creation_to_dict(creation)
    assert "created_at" in cdict and "updated_at" in cdict


def test_settings_mapper_roundtrip_defaults_and_custom() -> None:
    # defaults
    exec_limits = SettingsMapper.execution_limits_from_dict(None)
    assert exec_limits.max_timeout_seconds == 300
    sec = SettingsMapper.security_settings_from_dict(None)
    assert sec.password_min_length == 8
    mon = SettingsMapper.monnitoring_settings_from_dict if False else SettingsMapper.monitoring_settings_from_dict  # type: ignore[attr-defined]
    mon_settings = mon(None)
    assert mon_settings.log_level is not None

    # to_dict/from_dict
    limits = ExecutionLimits(max_timeout_seconds=10, max_memory_mb=256, max_cpu_cores=1, max_concurrent_executions=2)
    sec = SecuritySettings(password_min_length=12, session_timeout_minutes=30, max_login_attempts=3, lockout_duration_minutes=5)
    mon = MonitoringSettings(metrics_retention_days=7, enable_tracing=False)
    sys = SystemSettings(execution_limits=limits, security_settings=sec, monitoring_settings=mon)

    sys_dict = SettingsMapper.system_settings_to_dict(sys)
    sys_back = SettingsMapper.system_settings_from_dict(sys_dict)
    assert sys_back.execution_limits.max_memory_mb == 256 and sys_back.monitoring_settings.enable_tracing is False

    # pydantic dict
    pyd = SettingsMapper.system_settings_to_pydantic_dict(sys)
    sys_back2 = SettingsMapper.system_settings_from_pydantic(pyd)
    assert sys_back2.security_settings.password_min_length == 12


def test_audit_log_mapper_roundtrip() -> None:
    entry = AuditLogEntry(
        action=AuditAction.SYSTEM_SETTINGS_UPDATED,
        user_id="u1",
        username="alice",
        timestamp=_now(),
        changes={"k": "v"},
        reason="init",
    )
    d = AuditLogMapper.to_dict(entry)
    e2 = AuditLogMapper.from_dict(d)
    assert e2.action == entry.action and e2.reason == "init"
