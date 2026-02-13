import redis.asyncio as redis
import structlog

from app.services.runtime_settings import RuntimeSettingsLoader


class LoginLockoutService:
    """Redis-backed login lockout tracking."""

    _PREFIX = "login_lockout"

    def __init__(
        self,
        redis_client: redis.Redis,
        runtime_settings: RuntimeSettingsLoader,
        logger: structlog.stdlib.BoundLogger,
    ) -> None:
        self._redis = redis_client
        self._runtime_settings = runtime_settings
        self._logger = logger

    def _attempts_key(self, username: str) -> str:
        return f"{self._PREFIX}:attempts:{username}"

    def _locked_key(self, username: str) -> str:
        return f"{self._PREFIX}:locked:{username}"

    async def check_locked(self, username: str) -> bool:
        return bool(await self._redis.exists(self._locked_key(username)))

    async def record_failed_attempt(self, username: str) -> bool:
        """Record a failed login attempt. Returns True if the account is now locked."""
        effective = await self._runtime_settings.get_effective_settings()
        ttl = effective.lockout_duration_minutes * 60

        attempts_key = self._attempts_key(username)
        attempts = await self._redis.incr(attempts_key)
        await self._redis.expire(attempts_key, ttl)

        if attempts >= effective.max_login_attempts:
            await self._redis.set(self._locked_key(username), "1", ex=ttl)
            self._logger.warning(
                "Account locked due to too many failed attempts",
                username=username,
                attempts=attempts,
            )
            return True

        return False

    async def clear_attempts(self, username: str) -> None:
        await self._redis.delete(self._attempts_key(username), self._locked_key(username))

    async def unlock_user(self, username: str) -> None:
        await self.clear_attempts(username)
