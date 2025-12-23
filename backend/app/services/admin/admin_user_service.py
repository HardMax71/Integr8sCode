from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.logging import logger
from app.core.security import SecurityService
from app.db.repositories.admin.admin_user_repository import AdminUserRepository
from app.domain.admin import AdminUserOverviewDomain, DerivedCountsDomain, RateLimitSummaryDomain
from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.user import UserRole
from app.domain.rate_limit import RateLimitUpdateResult, UserRateLimit, UserRateLimitsResult
from app.domain.user import PasswordReset, User, UserListResult, UserUpdate
from app.infrastructure.mappers import UserRateLimitMapper
from app.schemas_pydantic.user import UserCreate
from app.services.event_service import EventService
from app.services.execution_service import ExecutionService
from app.services.rate_limit_service import RateLimitService


class AdminUserService:
    def __init__(
        self,
        user_repository: AdminUserRepository,
        event_service: EventService,
        execution_service: ExecutionService,
        rate_limit_service: RateLimitService,
    ) -> None:
        self._users = user_repository
        self._events = event_service
        self._executions = execution_service
        self._rate_limits = rate_limit_service

    async def get_user_overview(self, user_id: str, hours: int = 24) -> AdminUserOverviewDomain:
        logger.info("Admin getting user overview", extra={"target_user_id": user_id, "hours": hours})
        user = await self._users.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=hours)
        stats_domain = await self._events.get_event_statistics(
            user_id=user_id,
            user_role=UserRole.ADMIN,
            start_time=start,
            end_time=now,
            include_all_users=False,
        )
        exec_stats = await self._executions.get_execution_stats(user_id=user_id, time_range=(start, now))
        by_status = exec_stats.get("by_status", {}) or {}

        def _count(status: ExecutionStatus) -> int:
            return int(by_status.get(status, 0) or by_status.get(status.value, 0) or 0)

        succeeded = _count(ExecutionStatus.COMPLETED)
        failed = _count(ExecutionStatus.FAILED)
        timeout = _count(ExecutionStatus.TIMEOUT)
        cancelled = _count(ExecutionStatus.CANCELLED)
        derived = DerivedCountsDomain(
            succeeded=succeeded,
            failed=failed,
            timeout=timeout,
            cancelled=cancelled,
            terminal_total=succeeded + failed + timeout + cancelled,
        )

        rl = await self._rate_limits.get_user_rate_limit(user_id)
        rl_summary = RateLimitSummaryDomain(
            bypass_rate_limit=rl.bypass_rate_limit if rl else False,
            global_multiplier=rl.global_multiplier if rl else 1.0,
            has_custom_limits=bool(rl.rules) if rl else False,
        )

        # Recent execution-related events (last 10)
        event_types: list[EventType] = [
            EventType.EXECUTION_REQUESTED,
            EventType.EXECUTION_STARTED,
            EventType.EXECUTION_COMPLETED,
            EventType.EXECUTION_FAILED,
            EventType.EXECUTION_TIMEOUT,
            EventType.EXECUTION_CANCELLED,
        ]
        recent_result = await self._events.get_user_events_paginated(
            user_id=user_id,
            event_types=[str(et) for et in event_types],
            start_time=start,
            end_time=now,
            limit=10,
            skip=0,
            sort_order="desc",
        )
        recent_events = recent_result.events

        return AdminUserOverviewDomain(
            user=user,
            stats=stats_domain,
            derived_counts=derived,
            rate_limit_summary=rl_summary,
            recent_events=recent_events,
        )

    async def list_users(
        self, *, admin_username: str, limit: int, offset: int, search: str | None, role: UserRole | None
    ) -> UserListResult:
        logger.info(
            "Admin listing users",
            extra={
                "admin_username": admin_username,
                "limit": limit,
                "offset": offset,
                "search": search,
                "role": role,
            },
        )

        return await self._users.list_users(limit=limit, offset=offset, search=search, role=role)

    async def create_user(self, *, admin_username: str, user_data: UserCreate) -> User:
        """Create a new user and return domain user."""
        logger.info(
            "Admin creating new user", extra={"admin_username": admin_username, "new_username": user_data.username}
        )
        # Ensure not exists
        search_result = await self._users.list_users(limit=1, offset=0, search=user_data.username)
        for user in search_result.users:
            if user.username == user_data.username:
                raise ValueError("Username already exists")

        security = SecurityService()
        hashed_password = security.get_password_hash(user_data.password)

        user_id = str(uuid4())  # imported where defined
        now = datetime.now(timezone.utc)
        user_doc = {
            "user_id": user_id,
            "username": user_data.username,
            "email": user_data.email,
            "hashed_password": hashed_password,
            "role": getattr(user_data, "role", UserRole.USER),
            "is_active": getattr(user_data, "is_active", True),
            "is_superuser": False,
            "created_at": now,
            "updated_at": now,
        }
        await self._users.users_collection.insert_one(user_doc)
        logger.info(
            "User created successfully", extra={"new_username": user_data.username, "admin_username": admin_username}
        )
        # Return fresh domain user
        created = await self._users.get_user_by_id(user_id)
        if not created:
            raise ValueError("Failed to fetch created user")
        return created

    async def get_user(self, *, admin_username: str, user_id: str) -> User | None:
        logger.info("Admin getting user details", extra={"admin_username": admin_username, "target_user_id": user_id})
        return await self._users.get_user_by_id(user_id)

    async def update_user(self, *, admin_username: str, user_id: str, update: UserUpdate) -> User | None:
        logger.info(
            "Admin updating user",
            extra={"admin_username": admin_username, "target_user_id": user_id},
        )
        return await self._users.update_user(user_id, update)

    async def delete_user(self, *, admin_username: str, user_id: str, cascade: bool) -> dict[str, int]:
        logger.info(
            "Admin deleting user",
            extra={"admin_username": admin_username, "target_user_id": user_id, "cascade": cascade},
        )
        # Reset rate limits prior to deletion
        await self._rate_limits.reset_user_limits(user_id)
        deleted_counts = await self._users.delete_user(user_id, cascade=cascade)
        if deleted_counts.get("user", 0) > 0:
            logger.info("User deleted successfully", extra={"target_user_id": user_id})
        return deleted_counts

    async def reset_user_password(self, *, admin_username: str, user_id: str, new_password: str) -> bool:
        logger.info(
            "Admin resetting user password", extra={"admin_username": admin_username, "target_user_id": user_id}
        )
        pr = PasswordReset(user_id=user_id, new_password=new_password)
        ok = await self._users.reset_user_password(pr)
        if ok:
            logger.info("User password reset successfully", extra={"target_user_id": user_id})
        return ok

    async def get_user_rate_limits(self, *, admin_username: str, user_id: str) -> UserRateLimitsResult:
        logger.info(
            "Admin getting user rate limits", extra={"admin_username": admin_username, "target_user_id": user_id}
        )
        user_limit = await self._rate_limits.get_user_rate_limit(user_id)
        usage_stats = await self._rate_limits.get_usage_stats(user_id)
        return UserRateLimitsResult(
            user_id=user_id,
            rate_limit_config=user_limit,
            current_usage=usage_stats,
        )

    async def update_user_rate_limits(
        self, *, admin_username: str, user_id: str, config: UserRateLimit
    ) -> RateLimitUpdateResult:
        mapper = UserRateLimitMapper()
        logger.info(
            "Admin updating user rate limits",
            extra={"admin_username": admin_username, "target_user_id": user_id, "config": mapper.to_dict(config)},
        )
        config.user_id = user_id
        await self._rate_limits.update_user_rate_limit(user_id, config)
        return RateLimitUpdateResult(user_id=user_id, updated=True, config=config)

    async def reset_user_rate_limits(self, *, admin_username: str, user_id: str) -> bool:
        logger.info(
            "Admin resetting user rate limits", extra={"admin_username": admin_username, "target_user_id": user_id}
        )
        await self._rate_limits.reset_user_limits(user_id)
        return True
