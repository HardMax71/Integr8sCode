import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from app.core.metrics import DatabaseMetrics
from app.domain.events import BaseEvent
from app.domain.idempotency import IdempotencyRecord, IdempotencyStatus, KeyStrategy
from app.services.idempotency.redis_repository import RedisIdempotencyRepository


class IdempotencyResult(BaseModel):
    is_duplicate: bool
    status: IdempotencyStatus
    created_at: datetime
    completed_at: datetime | None = None
    processing_duration_ms: int | None = None
    error: str | None = None
    has_cached_result: bool = False
    key: str


class IdempotencyConfig(BaseModel):
    key_prefix: str = "idempotency"
    default_ttl_seconds: int = 3600
    processing_timeout_seconds: int = 300
    enable_result_caching: bool = True
    max_result_size_bytes: int = 1048576


class IdempotencyManager:
    def __init__(
        self,
        config: IdempotencyConfig,
        repository: RedisIdempotencyRepository,
        logger: logging.Logger,
        database_metrics: DatabaseMetrics,
    ) -> None:
        self.config = config
        self.metrics = database_metrics
        self._repo = repository
        self.logger = logger
        self.logger.info("Idempotency manager initialized")

    def _generate_key(
        self, event: BaseEvent, key_strategy: KeyStrategy, custom_key: str | None = None, fields: set[str] | None = None
    ) -> str:
        if key_strategy == KeyStrategy.EVENT_BASED:
            key = f"{event.event_type}:{event.event_id}"
        elif key_strategy == KeyStrategy.CONTENT_HASH:
            event_dict = event.model_dump(mode="json")
            event_dict.pop("event_id", None)
            event_dict.pop("timestamp", None)
            event_dict.pop("metadata", None)
            if fields:
                event_dict = {k: v for k, v in event_dict.items() if k in fields}
            content = json.dumps(event_dict, sort_keys=True)
            key = hashlib.sha256(content.encode()).hexdigest()
        elif key_strategy == KeyStrategy.CUSTOM and custom_key:
            key = f"{event.event_type}:{custom_key}"
        else:
            raise ValueError(f"Invalid key strategy: {key_strategy}")
        return f"{self.config.key_prefix}:{key}"

    async def check_and_reserve(
        self,
        event: BaseEvent,
        key_strategy: KeyStrategy = KeyStrategy.EVENT_BASED,
        custom_key: str | None = None,
        ttl_seconds: int | None = None,
        fields: set[str] | None = None,
    ) -> IdempotencyResult:
        full_key = self._generate_key(event, key_strategy, custom_key, fields)
        ttl = ttl_seconds or self.config.default_ttl_seconds

        existing = await self._repo.find_by_key(full_key)
        if existing:
            self.metrics.record_idempotency_cache_hit(event.event_type, "check_and_reserve")
            return await self._handle_existing_key(existing, full_key, event.event_type)

        self.metrics.record_idempotency_cache_miss(event.event_type, "check_and_reserve")
        return await self._create_new_key(full_key, event, ttl)

    async def _handle_existing_key(
        self,
        existing: IdempotencyRecord,
        full_key: str,
        event_type: str,
    ) -> IdempotencyResult:
        status = existing.status
        if status == IdempotencyStatus.PROCESSING:
            return await self._handle_processing_key(existing, full_key, event_type)

        self.metrics.record_idempotency_duplicate_blocked(event_type)
        created_at = existing.created_at or datetime.now(timezone.utc)
        return IdempotencyResult(
            is_duplicate=True,
            status=status,
            created_at=created_at,
            completed_at=existing.completed_at,
            processing_duration_ms=existing.processing_duration_ms,
            error=existing.error,
            has_cached_result=existing.result_json is not None,
            key=full_key,
        )

    async def _handle_processing_key(
        self,
        existing: IdempotencyRecord,
        full_key: str,
        event_type: str,
    ) -> IdempotencyResult:
        created_at = existing.created_at
        now = datetime.now(timezone.utc)

        if now - created_at > timedelta(seconds=self.config.processing_timeout_seconds):
            self.logger.warning(f"Idempotency key {full_key} processing timeout, allowing retry")
            existing.created_at = now
            existing.status = IdempotencyStatus.PROCESSING
            await self._repo.update_record(existing)
            return IdempotencyResult(
                is_duplicate=False, status=IdempotencyStatus.PROCESSING, created_at=now, key=full_key
            )

        self.metrics.record_idempotency_duplicate_blocked(event_type)
        return IdempotencyResult(
            is_duplicate=True,
            status=IdempotencyStatus.PROCESSING,
            created_at=created_at,
            has_cached_result=existing.result_json is not None,
            key=full_key,
        )

    async def _create_new_key(self, full_key: str, event: BaseEvent, ttl: int) -> IdempotencyResult:
        created_at = datetime.now(timezone.utc)
        try:
            record = IdempotencyRecord(
                key=full_key,
                status=IdempotencyStatus.PROCESSING,
                event_type=event.event_type,
                event_id=str(event.event_id),
                created_at=created_at,
                ttl_seconds=ttl,
            )
            await self._repo.insert_processing(record)
            self.metrics.increment_idempotency_keys(self.config.key_prefix)
            return IdempotencyResult(
                is_duplicate=False, status=IdempotencyStatus.PROCESSING, created_at=created_at, key=full_key
            )
        except DuplicateKeyError:
            # Race: someone inserted the same key concurrently — treat as existing
            existing = await self._repo.find_by_key(full_key)
            if existing:
                return await self._handle_existing_key(existing, full_key, event.event_type)
            # If for some reason it's still not found, allow processing
            return IdempotencyResult(
                is_duplicate=False, status=IdempotencyStatus.PROCESSING, created_at=created_at, key=full_key
            )

    async def _update_key_status(
        self,
        full_key: str,
        existing: IdempotencyRecord,
        status: IdempotencyStatus,
        cached_json: str | None = None,
        error: str | None = None,
    ) -> bool:
        created_at = existing.created_at
        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - created_at).total_seconds() * 1000)
        existing.status = status
        existing.completed_at = completed_at
        existing.processing_duration_ms = duration_ms
        if error:
            existing.error = error
        if cached_json is not None and self.config.enable_result_caching:
            if len(cached_json.encode()) <= self.config.max_result_size_bytes:
                existing.result_json = cached_json
            else:
                self.logger.warning(f"Result too large to cache for key {full_key}")
        return (await self._repo.update_record(existing)) > 0

    async def mark_completed(
        self,
        event: BaseEvent,
        key_strategy: KeyStrategy = KeyStrategy.EVENT_BASED,
        custom_key: str | None = None,
        fields: set[str] | None = None,
    ) -> bool:
        full_key = self._generate_key(event, key_strategy, custom_key, fields)
        try:
            existing = await self._repo.find_by_key(full_key)
        except Exception as e:  # Narrow DB op
            self.logger.error(f"Failed to load idempotency key for completion: {e}")
            return False
        if not existing:
            self.logger.warning(f"Idempotency key {full_key} not found when marking completed")
            return False
        return await self._update_key_status(full_key, existing, IdempotencyStatus.COMPLETED, cached_json=None)

    async def mark_failed(
        self,
        event: BaseEvent,
        error: str,
        key_strategy: KeyStrategy = KeyStrategy.EVENT_BASED,
        custom_key: str | None = None,
        fields: set[str] | None = None,
    ) -> bool:
        full_key = self._generate_key(event, key_strategy, custom_key, fields)
        existing = await self._repo.find_by_key(full_key)
        if not existing:
            self.logger.warning(f"Idempotency key {full_key} not found when marking failed")
            return False
        return await self._update_key_status(
            full_key, existing, IdempotencyStatus.FAILED, cached_json=None, error=error
        )

    async def mark_completed_with_json(
        self,
        event: BaseEvent,
        cached_json: str,
        key_strategy: KeyStrategy = KeyStrategy.EVENT_BASED,
        custom_key: str | None = None,
        fields: set[str] | None = None,
    ) -> bool:
        full_key = self._generate_key(event, key_strategy, custom_key, fields)
        existing = await self._repo.find_by_key(full_key)
        if not existing:
            self.logger.warning(f"Idempotency key {full_key} not found when marking completed with cache")
            return False
        return await self._update_key_status(full_key, existing, IdempotencyStatus.COMPLETED, cached_json=cached_json)

    async def get_cached_json(
        self, event: BaseEvent, key_strategy: KeyStrategy, custom_key: str | None, fields: set[str] | None = None
    ) -> str:
        full_key = self._generate_key(event, key_strategy, custom_key, fields)
        existing = await self._repo.find_by_key(full_key)
        assert existing and existing.result_json is not None, "Invariant: cached result must exist when requested"
        return existing.result_json
