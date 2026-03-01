from time import monotonic

import structlog

from app.db import AdminSettingsRepository
from app.domain.admin import SystemSettings
from app.settings import Settings


class RuntimeSettingsLoader:
    """Loads effective system settings from DB with TOML fallback.

    APP-scoped service with a 60-second in-memory cache.
    """

    def __init__(
        self,
        repo: AdminSettingsRepository,
        settings: Settings,
        logger: structlog.stdlib.BoundLogger,
    ) -> None:
        self._repo = repo
        self._settings = settings
        self._logger = logger
        self._cache: SystemSettings | None = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 60.0

    async def get_effective_settings(self) -> SystemSettings:
        now = monotonic()
        if self._cache is not None and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        try:
            toml_defaults = self._build_toml_defaults()
            result = await self._repo.get_system_settings(defaults=toml_defaults)
        except Exception:
            self._logger.warning("Failed to load settings from DB, falling back to TOML defaults", exc_info=True)
            result = self._build_toml_defaults()

        self._cache = result
        self._cache_time = monotonic()
        return result

    def invalidate_cache(self) -> None:
        self._cache = None

    def _build_toml_defaults(self) -> SystemSettings:
        s = self._settings
        return SystemSettings(
            max_timeout_seconds=s.K8S_POD_EXECUTION_TIMEOUT,
            memory_limit=s.K8S_POD_MEMORY_LIMIT,
            cpu_limit=s.K8S_POD_CPU_LIMIT,
            max_concurrent_executions=s.K8S_MAX_CONCURRENT_PODS,
            session_timeout_minutes=s.ACCESS_TOKEN_EXPIRE_MINUTES,
        )
