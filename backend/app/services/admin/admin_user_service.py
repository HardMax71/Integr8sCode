from datetime import datetime, timedelta, timezone

import structlog

from app.core.security import SecurityService
from app.db.repositories import UserRepository
from app.domain.admin import AdminUserOverviewDomain, DerivedCountsDomain, RateLimitSummaryDomain
from app.domain.enums import EventType, ExecutionStatus, UserRole
from app.domain.exceptions import ConflictError, NotFoundError
from app.domain.rate_limit import RateLimitUpdateResult, UserRateLimit, UserRateLimitsResult, UserRateLimitUpdate
from app.domain.user import (
    DomainUserCreate,
    DomainUserUpdate,
    PasswordReset,
    User,
    UserDeleteResult,
    UserListResult,
    UserUpdate,
)
from app.services.event_service import EventService
from app.services.execution_service import ExecutionService
from app.services.rate_limit_service import RateLimitService


class AdminUserService:
    def __init__(
        self,
        user_repository: UserRepository,
        event_service: EventService,
        execution_service: ExecutionService,
        rate_limit_service: RateLimitService,
        security_service: SecurityService,
        logger: structlog.stdlib.BoundLogger,
    ) -> None:
        self._users = user_repository
        self._events = event_service
        self._executions = execution_service
        self._rate_limits = rate_limit_service
        self._security = security_service
        self.logger = logger

    async def get_user_overview(self, user_id: str, hours: int = 24) -> AdminUserOverviewDomain:
        self.logger.info("Admin getting user overview", target_user_id=user_id, hours=hours)
        user = await self._users.get_user_by_id(user_id)
        if not user:
            raise NotFoundError("User", user_id)

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
            return int(by_status.get(status, 0) or 0)

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
            event_types=event_types,
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
        self, *, admin_user_id: str, limit: int, offset: int, search: str | None, role: UserRole | None
    ) -> UserListResult:
        self.logger.info(
            "Admin listing users",
            admin_user_id=admin_user_id,
            limit=limit,
            offset=offset,
            search=search,
            role=role,
        )

        result = await self._users.list_users(limit=limit, offset=offset, search=search, role=role)

        # Enrich users with rate limit summaries
        summaries = await self._rate_limits.get_user_rate_limit_summaries([u.user_id for u in result.users])
        enriched_users = [
            user.model_copy(update={
                "bypass_rate_limit": s.bypass_rate_limit,
                "global_multiplier": s.global_multiplier,
                "has_custom_limits": s.has_custom_limits,
            }) if (s := summaries.get(user.user_id)) else user
            for user in result.users
        ]

        return UserListResult(users=enriched_users, total=result.total, offset=result.offset, limit=result.limit)

    async def create_user(
        self,
        *,
        admin_user_id: str,
        username: str,
        email: str,
        password: str,
        role: UserRole = UserRole.USER,
        is_active: bool = True,
    ) -> User:
        self.logger.info("Admin creating new user", admin_user_id=admin_user_id, new_username=username)
        existing = await self._users.get_user(username)
        if existing:
            raise ConflictError("Username already exists")

        create_data = DomainUserCreate(
            username=username,
            email=email,
            hashed_password=self._security.get_password_hash(password),
            role=role,
            is_active=is_active,
        )
        created = await self._users.create_user(create_data)
        self.logger.info("User created successfully", new_username=username, admin_user_id=admin_user_id)
        return created

    async def get_user(self, *, admin_user_id: str, user_id: str) -> User | None:
        self.logger.info(
            "Admin getting user details", admin_user_id=admin_user_id, target_user_id=user_id
        )
        return await self._users.get_user_by_id(user_id)

    async def update_user(self, *, admin_user_id: str, user_id: str, update: UserUpdate) -> User | None:
        self.logger.info(
            "Admin updating user",
            admin_user_id=admin_user_id,
            target_user_id=user_id,
        )
        hashed_password = self._security.get_password_hash(update.password) if update.password else None
        domain_update = DomainUserUpdate(
            username=update.username,
            email=update.email,
            role=update.role,
            is_active=update.is_active,
            hashed_password=hashed_password,
        )
        return await self._users.update_user(user_id, domain_update)

    async def delete_user(self, *, admin_user_id: str, user_id: str, cascade: bool) -> UserDeleteResult:
        self.logger.info(
            "Admin deleting user",
            admin_user_id=admin_user_id,
            target_user_id=user_id,
            cascade=cascade,
        )
        # Reset rate limits prior to deletion
        await self._rate_limits.reset_user_limits(user_id)
        result = await self._users.delete_user(user_id, cascade=cascade)
        if result.user_deleted:
            self.logger.info("User deleted successfully", target_user_id=user_id)
        return result

    async def reset_user_password(self, *, admin_user_id: str, user_id: str, new_password: str) -> bool:
        self.logger.info(
            "Admin resetting user password", admin_user_id=admin_user_id, target_user_id=user_id
        )
        hashed = self._security.get_password_hash(new_password)
        pr = PasswordReset(user_id=user_id, new_password=hashed)
        ok = await self._users.reset_user_password(pr)
        if ok:
            self.logger.info("User password reset successfully", target_user_id=user_id)
        return ok

    async def get_user_rate_limits(self, *, admin_user_id: str, user_id: str) -> UserRateLimitsResult:
        self.logger.info(
            "Admin getting user rate limits", admin_user_id=admin_user_id, target_user_id=user_id
        )
        user_limit = await self._rate_limits.get_user_rate_limit(user_id)
        usage_stats = await self._rate_limits.get_usage_stats(user_id)
        return UserRateLimitsResult(
            user_id=user_id,
            rate_limit_config=user_limit,
            current_usage=usage_stats,
        )

    async def update_user_rate_limits(
        self, *, admin_user_id: str, user_id: str, update: UserRateLimitUpdate
    ) -> RateLimitUpdateResult:
        self.logger.info(
            "Admin updating user rate limits",
            admin_user_id=admin_user_id,
            target_user_id=user_id,
        )
        config = UserRateLimit(
            user_id=user_id,
            rules=update.rules,
            bypass_rate_limit=update.bypass_rate_limit,
            global_multiplier=update.global_multiplier,
            notes=update.notes,
        )
        await self._rate_limits.update_user_rate_limit(user_id, config)
        return RateLimitUpdateResult(user_id=user_id, updated=True, config=config)

    async def reset_user_rate_limits(self, *, admin_user_id: str, user_id: str) -> bool:
        self.logger.info(
            "Admin resetting user rate limits", admin_user_id=admin_user_id, target_user_id=user_id
        )
        await self._rate_limits.reset_user_limits(user_id)
        return True
