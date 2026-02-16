from datetime import timedelta
from typing import NoReturn

import structlog
from fastapi import Request

from app.core.metrics import SecurityMetrics
from app.core.security import SecurityService
from app.db.repositories import UserRepository
from app.domain.enums import LoginMethod, UserRole
from app.domain.events import (
    AuthFailedEvent,
    EventMetadata,
    UserLoggedInEvent,
    UserLoggedOutEvent,
    UserRegisteredEvent,
)
from app.domain.exceptions import AccountLockedError, ConflictError, ValidationError
from app.domain.user import (
    AdminAccessRequiredError,
    AuthenticationRequiredError,
    DomainUserCreate,
    InvalidCredentialsError,
    LoginResult,
    User,
)
from app.events.core import UnifiedProducer
from app.services.login_lockout import LoginLockoutService
from app.services.runtime_settings import RuntimeSettingsLoader
from app.settings import Settings


class AuthService:
    def __init__(
        self,
        user_repo: UserRepository,
        security_service: SecurityService,
        security_metrics: SecurityMetrics,
        logger: structlog.stdlib.BoundLogger,
        lockout_service: LoginLockoutService,
        runtime_settings: RuntimeSettingsLoader,
        producer: UnifiedProducer,
        settings: Settings,
    ):
        self.user_repo = user_repo
        self.security_service = security_service
        self.security_metrics = security_metrics
        self.logger = logger
        self._lockout = lockout_service
        self._runtime_settings = runtime_settings
        self._producer = producer
        self._settings = settings

    def _build_metadata(self, user_id: str = "") -> EventMetadata:
        return EventMetadata(
            service_name=self._settings.SERVICE_NAME,
            service_version=self._settings.SERVICE_VERSION,
            user_id=user_id,
        )

    async def get_current_user(self, request: Request) -> User:
        token = request.cookies.get("access_token")
        if not token:
            raise AuthenticationRequiredError()

        username = self.security_service.decode_token(token)

        user = await self.user_repo.get_user(username)
        if user is None:
            raise InvalidCredentialsError()

        return user

    async def get_admin(self, request: Request) -> User:
        user = await self.get_current_user(request)
        self.security_metrics.record_authorization_check(
            "/admin", request.method, user.role == UserRole.ADMIN, user_role=user.role,
        )
        if user.role != UserRole.ADMIN:
            self.logger.warning(f"Admin access denied for user: {user.username} (role: {user.role})")
            raise AdminAccessRequiredError(user.username)
        return user

    async def _fail_login(
        self,
        username: str,
        reason: str,
        ip_address: str,
        user_agent: str | None,
        user_id: str = "",
    ) -> NoReturn:
        self.logger.warning(
            f"Login failed - {reason}",
            username=username,
            client_ip=ip_address,
            user_agent=user_agent,
        )
        locked = await self._lockout.record_failed_attempt(username)
        await self._producer.produce(
            event_to_produce=AuthFailedEvent(
                username=username,
                reason=reason,
                ip_address=ip_address,
                metadata=self._build_metadata(user_id=user_id),
            ),
            key=username,
        )
        if locked:
            self.security_metrics.record_account_locked(username, "brute_force")
            raise AccountLockedError("Account locked due to too many failed attempts")
        raise InvalidCredentialsError()

    async def login(
        self,
        username: str,
        password: str,
        ip_address: str,
        user_agent: str | None,
    ) -> LoginResult:
        if await self._lockout.check_locked(username):
            raise AccountLockedError("Account temporarily locked due to too many failed attempts")

        user = await self.user_repo.get_user(username)

        if not user:
            await self._fail_login(username, "user_not_found", ip_address, user_agent)

        if not self.security_service.verify_password(password, user.hashed_password):
            await self._fail_login(username, "invalid_password", ip_address, user_agent, user_id=str(user.user_id))

        await self._lockout.clear_attempts(username)

        effective = await self._runtime_settings.get_effective_settings()
        session_timeout = effective.session_timeout_minutes

        self.logger.info(
            "Login successful",
            username=user.username,
            client_ip=ip_address,
            user_agent=user_agent,
            token_expires_in_minutes=session_timeout,
        )

        access_token_expires = timedelta(minutes=session_timeout)
        access_token = self.security_service.create_access_token(
            data={"sub": user.username}, expires_delta=access_token_expires,
        )
        csrf_token = self.security_service.generate_csrf_token(access_token)

        await self._producer.produce(
            event_to_produce=UserLoggedInEvent(
                user_id=str(user.user_id),
                login_method=LoginMethod.PASSWORD,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata=self._build_metadata(user_id=str(user.user_id)),
            ),
            key=user.username,
        )

        return LoginResult(
            username=user.username,
            role=user.role,
            access_token=access_token,
            csrf_token=csrf_token,
            session_timeout_minutes=session_timeout,
        )

    async def register(
        self,
        username: str,
        email: str,
        password: str,
        ip_address: str,
        user_agent: str | None,
    ) -> User:
        effective = await self._runtime_settings.get_effective_settings()
        min_len = effective.password_min_length
        if len(password) < min_len:
            self.security_metrics.record_weak_password_attempt(username, "too_short")
            raise ValidationError(f"Password must be at least {min_len} characters")

        existing = await self.user_repo.get_user(username)
        if existing:
            self.logger.warning(
                "Registration failed - username taken",
                username=username,
                client_ip=ip_address,
                user_agent=user_agent,
            )
            raise ConflictError("Username already registered")

        hashed_password = self.security_service.get_password_hash(password)
        create_data = DomainUserCreate(
            username=username,
            email=email,
            hashed_password=hashed_password,
            role=UserRole.USER,
            is_active=True,
            is_superuser=False,
        )
        created_user = await self.user_repo.create_user(create_data)

        self.logger.info(
            "Registration successful",
            username=created_user.username,
            client_ip=ip_address,
            user_agent=user_agent,
        )

        await self._producer.produce(
            event_to_produce=UserRegisteredEvent(
                user_id=str(created_user.user_id),
                username=created_user.username,
                email=created_user.email,
                metadata=self._build_metadata(user_id=str(created_user.user_id)),
            ),
            key=created_user.username,
        )

        return created_user

    async def publish_logout_event(self, token: str | None) -> None:
        if not token:
            return
        username = self.security_service.decode_token(token)
        await self._producer.produce(
            event_to_produce=UserLoggedOutEvent(
                user_id=username,
                logout_reason="user_initiated",
                metadata=self._build_metadata(user_id=username),
            ),
            key=username,
        )
