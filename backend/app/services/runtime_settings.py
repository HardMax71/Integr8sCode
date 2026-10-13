from time import monotonic

import structlog
from pydantic import ValidationError
from pymongo.errors import PyMongoError

from app.db import AdminSettingsRepository
from app.domain.admin import SystemSettings
from app.domain.execution import LanguageLimitsDomain
from app.runtime_registry import POD_RUNTIME_CONFIGS, PodRuntimeConfig, at_least
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
            result = await self._repo.get_system_settings(defaults=self._build_toml_defaults())
        except PyMongoError, ValidationError:
            self._logger.warning("Failed to load settings from DB, falling back to TOML defaults", exc_info=True)
            result = self._build_toml_defaults()

        self._cache = result
        self._cache_time = monotonic()
        return result

    async def get_language_limits(self, language: str) -> LanguageLimitsDomain:
        """Return the limits a pod for ``language`` gets, decided the same way as the pod builder.

        The admin limit (TOML when unset) is raised to the language minimum from the runtime registry.
        """
        effective = await self.get_effective_settings()
        pod_config = POD_RUNTIME_CONFIGS.get(language, PodRuntimeConfig())
        return LanguageLimitsDomain(
            cpu_limit=at_least(effective.cpu_limit or self._settings.K8S_POD_CPU_LIMIT, pod_config.min_cpu),
            memory_limit=at_least(effective.memory_limit or self._settings.K8S_POD_MEMORY_LIMIT, pod_config.min_memory),
            execution_timeout=pod_config.timeout_for(effective.max_timeout_seconds),
        )

    def invalidate_cache(self) -> None:
        self._cache = None

    def _build_toml_defaults(self) -> SystemSettings:
        s = self._settings
        return SystemSettings(
            max_timeout_seconds=s.K8S_POD_EXECUTION_TIMEOUT,
            memory_limit=s.K8S_POD_MEMORY_LIMIT,
            cpu_limit=s.K8S_POD_CPU_LIMIT,
            session_timeout_minutes=s.ACCESS_TOKEN_EXPIRE_MINUTES,
        )
