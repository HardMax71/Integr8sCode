import re
from datetime import datetime, timezone
from typing import Any, Dict

from app.domain.admin import (
    AuditAction,
    AuditLogEntry,
    AuditLogFields,
    ExecutionLimits,
    LogLevel,
    MonitoringSettings,
    SecuritySettings,
    SettingsFields,
    SystemSettings,
)
from app.domain.user import (
    User as DomainAdminUser,
)
from app.domain.user import (
    UserCreation,
    UserFields,
    UserListResult,
    UserRole,
    UserSearchFilter,
    UserUpdate,
)
from app.schemas_pydantic.user import User as ServiceUser

EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


class UserMapper:
    @staticmethod
    def to_mongo_document(user: DomainAdminUser) -> Dict[str, Any]:
        return {
            UserFields.USER_ID: user.user_id,
            UserFields.USERNAME: user.username,
            UserFields.EMAIL: user.email,
            UserFields.ROLE: user.role.value,
            UserFields.IS_ACTIVE: user.is_active,
            UserFields.IS_SUPERUSER: user.is_superuser,
            UserFields.HASHED_PASSWORD: user.hashed_password,
            UserFields.CREATED_AT: user.created_at,
            UserFields.UPDATED_AT: user.updated_at,
        }

    @staticmethod
    def from_mongo_document(data: Dict[str, Any]) -> DomainAdminUser:
        required_fields = [UserFields.USER_ID, UserFields.USERNAME, UserFields.EMAIL]
        for field in required_fields:
            if field not in data or not data[field]:
                raise ValueError(f"Missing required field: {field}")

        email = data[UserFields.EMAIL]
        if not EMAIL_PATTERN.match(email):
            raise ValueError(f"Invalid email format: {email}")

        return DomainAdminUser(
            user_id=data[UserFields.USER_ID],
            username=data[UserFields.USERNAME],
            email=email,
            role=UserRole(data.get(UserFields.ROLE, UserRole.USER)),
            is_active=data.get(UserFields.IS_ACTIVE, True),
            is_superuser=data.get(UserFields.IS_SUPERUSER, False),
            hashed_password=data.get(UserFields.HASHED_PASSWORD, ""),
            created_at=data.get(UserFields.CREATED_AT, datetime.now(timezone.utc)),
            updated_at=data.get(UserFields.UPDATED_AT, datetime.now(timezone.utc)),
        )

    @staticmethod
    def to_response_dict(user: DomainAdminUser) -> Dict[str, Any]:
        created_at_ts = user.created_at.timestamp() if user.created_at else 0.0
        updated_at_ts = user.updated_at.timestamp() if user.updated_at else 0.0

        return {
            "user_id": user.user_id,
            "username": user.username,
            "email": user.email,
            "role": user.role.value,
            "is_active": user.is_active,
            "is_superuser": user.is_superuser,
            "created_at": created_at_ts,
            "updated_at": updated_at_ts,
        }

    @staticmethod
    def from_pydantic_service_user(user: ServiceUser) -> DomainAdminUser:
        """Convert internal service Pydantic user to domain admin user."""
        return DomainAdminUser(
            user_id=user.user_id,
            username=user.username,
            email=str(user.email),
            role=user.role,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            hashed_password="",
            created_at=user.created_at or datetime.now(timezone.utc),
            updated_at=user.updated_at or datetime.now(timezone.utc),
        )

    @staticmethod
    def to_update_dict(update: UserUpdate) -> Dict[str, Any]:
        update_dict: Dict[str, Any] = {}

        if update.username is not None:
            update_dict[UserFields.USERNAME] = update.username
        if update.email is not None:
            if not EMAIL_PATTERN.match(update.email):
                raise ValueError(f"Invalid email format: {update.email}")
            update_dict[UserFields.EMAIL] = update.email
        if update.role is not None:
            update_dict[UserFields.ROLE] = update.role.value
        if update.is_active is not None:
            update_dict[UserFields.IS_ACTIVE] = update.is_active

        return update_dict

    @staticmethod
    def search_filter_to_query(f: UserSearchFilter) -> Dict[str, Any]:
        query: Dict[str, Any] = {}
        if f.search_text:
            query["$or"] = [
                {UserFields.USERNAME.value: {"$regex": f.search_text, "$options": "i"}},
                {UserFields.EMAIL.value: {"$regex": f.search_text, "$options": "i"}},
            ]
        if f.role:
            query[UserFields.ROLE] = f.role
        return query

    @staticmethod
    def user_creation_to_dict(creation: UserCreation) -> Dict[str, Any]:
        return {
            UserFields.USERNAME: creation.username,
            UserFields.EMAIL: creation.email,
            UserFields.ROLE: creation.role.value,
            UserFields.IS_ACTIVE: creation.is_active,
            UserFields.IS_SUPERUSER: creation.is_superuser,
            UserFields.CREATED_AT: datetime.now(timezone.utc),
            UserFields.UPDATED_AT: datetime.now(timezone.utc),
        }


class UserListResultMapper:
    @staticmethod
    def to_dict(result: UserListResult) -> Dict[str, Any]:
        user_mapper = UserMapper()
        return {
            "users": [user_mapper.to_response_dict(user) for user in result.users],
            "total": result.total,
            "offset": result.offset,
            "limit": result.limit,
        }


class SettingsMapper:
    @staticmethod
    def execution_limits_to_dict(limits: ExecutionLimits) -> dict[str, int]:
        return {
            "max_timeout_seconds": limits.max_timeout_seconds,
            "max_memory_mb": limits.max_memory_mb,
            "max_cpu_cores": limits.max_cpu_cores,
            "max_concurrent_executions": limits.max_concurrent_executions,
        }

    @staticmethod
    def execution_limits_from_dict(data: dict[str, Any] | None) -> ExecutionLimits:
        if not data:
            return ExecutionLimits()
        return ExecutionLimits(
            max_timeout_seconds=data.get("max_timeout_seconds", 300),
            max_memory_mb=data.get("max_memory_mb", 512),
            max_cpu_cores=data.get("max_cpu_cores", 2),
            max_concurrent_executions=data.get("max_concurrent_executions", 10),
        )

    @staticmethod
    def security_settings_to_dict(settings: SecuritySettings) -> dict[str, int]:
        return {
            "password_min_length": settings.password_min_length,
            "session_timeout_minutes": settings.session_timeout_minutes,
            "max_login_attempts": settings.max_login_attempts,
            "lockout_duration_minutes": settings.lockout_duration_minutes,
        }

    @staticmethod
    def security_settings_from_dict(data: dict[str, Any] | None) -> SecuritySettings:
        if not data:
            return SecuritySettings()
        return SecuritySettings(
            password_min_length=data.get("password_min_length", 8),
            session_timeout_minutes=data.get("session_timeout_minutes", 60),
            max_login_attempts=data.get("max_login_attempts", 5),
            lockout_duration_minutes=data.get("lockout_duration_minutes", 15),
        )

    @staticmethod
    def monitoring_settings_to_dict(settings: MonitoringSettings) -> dict[str, Any]:
        return {
            "metrics_retention_days": settings.metrics_retention_days,
            "log_level": settings.log_level.value,
            "enable_tracing": settings.enable_tracing,
            "sampling_rate": settings.sampling_rate,
        }

    @staticmethod
    def monitoring_settings_from_dict(data: dict[str, Any] | None) -> MonitoringSettings:
        if not data:
            return MonitoringSettings()
        return MonitoringSettings(
            metrics_retention_days=data.get("metrics_retention_days", 30),
            log_level=LogLevel(data.get("log_level", LogLevel.INFO)),
            enable_tracing=data.get("enable_tracing", True),
            sampling_rate=data.get("sampling_rate", 0.1),
        )

    @staticmethod
    def system_settings_to_dict(settings: SystemSettings) -> dict[str, Any]:
        mapper = SettingsMapper()
        return {
            SettingsFields.EXECUTION_LIMITS: mapper.execution_limits_to_dict(settings.execution_limits),
            SettingsFields.SECURITY_SETTINGS: mapper.security_settings_to_dict(settings.security_settings),
            SettingsFields.MONITORING_SETTINGS: mapper.monitoring_settings_to_dict(settings.monitoring_settings),
            SettingsFields.CREATED_AT: settings.created_at,
            SettingsFields.UPDATED_AT: settings.updated_at,
        }

    @staticmethod
    def system_settings_from_dict(data: dict[str, Any] | None) -> SystemSettings:
        if not data:
            return SystemSettings()
        mapper = SettingsMapper()
        return SystemSettings(
            execution_limits=mapper.execution_limits_from_dict(data.get(SettingsFields.EXECUTION_LIMITS)),
            security_settings=mapper.security_settings_from_dict(data.get(SettingsFields.SECURITY_SETTINGS)),
            monitoring_settings=mapper.monitoring_settings_from_dict(data.get(SettingsFields.MONITORING_SETTINGS)),
            created_at=data.get(SettingsFields.CREATED_AT, datetime.now(timezone.utc)),
            updated_at=data.get(SettingsFields.UPDATED_AT, datetime.now(timezone.utc)),
        )

    @staticmethod
    def system_settings_to_pydantic_dict(settings: SystemSettings) -> dict[str, Any]:
        mapper = SettingsMapper()
        return {
            "execution_limits": mapper.execution_limits_to_dict(settings.execution_limits),
            "security_settings": mapper.security_settings_to_dict(settings.security_settings),
            "monitoring_settings": mapper.monitoring_settings_to_dict(settings.monitoring_settings),
        }

    @staticmethod
    def system_settings_from_pydantic(data: dict[str, Any]) -> SystemSettings:
        mapper = SettingsMapper()
        return SystemSettings(
            execution_limits=mapper.execution_limits_from_dict(data.get("execution_limits")),
            security_settings=mapper.security_settings_from_dict(data.get("security_settings")),
            monitoring_settings=mapper.monitoring_settings_from_dict(data.get("monitoring_settings")),
        )


class AuditLogMapper:
    @staticmethod
    def to_dict(entry: AuditLogEntry) -> dict[str, Any]:
        return {
            AuditLogFields.TIMESTAMP: entry.timestamp,
            AuditLogFields.ACTION: entry.action.value,
            AuditLogFields.USER_ID: entry.user_id,
            AuditLogFields.USERNAME: entry.username,
            AuditLogFields.CHANGES: entry.changes,
            "reason": entry.reason,  # reason is not in the enum but used as additional field
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> AuditLogEntry:
        return AuditLogEntry(
            timestamp=data.get(AuditLogFields.TIMESTAMP, datetime.now(timezone.utc)),
            action=AuditAction(data[AuditLogFields.ACTION]),
            user_id=data[AuditLogFields.USER_ID],
            username=data.get(AuditLogFields.USERNAME, ""),
            changes=data.get(AuditLogFields.CHANGES, {}),
            reason=data.get("reason", ""),
        )
