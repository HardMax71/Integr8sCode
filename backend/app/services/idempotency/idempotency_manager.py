import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import cast

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from app.core.logging import logger
from app.core.metrics.context import get_database_metrics
from app.core.utils import StringEnum
from app.db.repositories.idempotency_repository import IdempotencyRepository
from app.infrastructure.kafka.events import BaseEvent


class IdempotencyStatus(StringEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class IdempotencyResult(BaseModel):
    is_duplicate: bool
    status: IdempotencyStatus
    created_at: datetime
    result: object | None = None
    error: str | None = None
    completed_at: datetime | None = None
    processing_duration_ms: int | None = None


class IdempotencyConfig(BaseModel):
    key_prefix: str = "idempotency"
    default_ttl_seconds: int = 3600
    processing_timeout_seconds: int = 300
    enable_result_caching: bool = True
    max_result_size_bytes: int = 1048576
    enable_metrics: bool = True
    collection_name: str = "idempotency_keys"


class IdempotencyKeyStrategy:
    @staticmethod
    def event_based(event: BaseEvent) -> str:
        return f"{event.event_type}:{event.event_id}"

    @staticmethod
    def content_hash(event: BaseEvent, fields: set[str] | None = None) -> str:
        event_dict = event.model_dump()
        event_dict.pop("event_id", None)
        event_dict.pop("timestamp", None)
        event_dict.pop("metadata", None)

        if fields:
            event_dict = {k: v for k, v in event_dict.items() if k in fields}

        content = json.dumps(event_dict, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()

    @staticmethod
    def custom(event: BaseEvent, custom_key: str) -> str:
        return f"{event.event_type}:{custom_key}"


class IdempotencyManager:
    def __init__(self, config: IdempotencyConfig, repository: IdempotencyRepository) -> None:
        self.config = config
        self.metrics = get_database_metrics()
        self._repo = repository
        self._stats_update_task: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        if self.config.enable_metrics and self._stats_update_task is None:
            self._stats_update_task = asyncio.create_task(self._update_stats_loop())
        logger.info("Idempotency manager ready")

    async def close(self) -> None:
        if self._stats_update_task:
            self._stats_update_task.cancel()
            try:
                await self._stats_update_task
            except asyncio.CancelledError:
                pass
        logger.info("Closed idempotency manager")

    def _generate_key(
            self,
            event: BaseEvent,
            key_strategy: str,
            custom_key: str | None = None,
            fields: set[str] | None = None
    ) -> str:
        if key_strategy == "event_based":
            key = IdempotencyKeyStrategy.event_based(event)
        elif key_strategy == "content_hash":
            key = IdempotencyKeyStrategy.content_hash(event, fields)
        elif key_strategy == "custom" and custom_key:
            key = IdempotencyKeyStrategy.custom(event, custom_key)
        else:
            raise ValueError(f"Invalid key strategy: {key_strategy}")
        return f"{self.config.key_prefix}:{key}"

    async def check_and_reserve(
            self,
            event: BaseEvent,
            key_strategy: str = "event_based",
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
            existing: dict[str, object],
            full_key: str,
            event_type: str,
    ) -> IdempotencyResult:
        sv0 = existing.get("status")
        st0 = sv0 if isinstance(sv0, IdempotencyStatus) else IdempotencyStatus(str(sv0))
        if st0 == IdempotencyStatus.PROCESSING:
            return await self._handle_processing_key(existing, full_key, event_type)

        self.metrics.record_idempotency_duplicate_blocked(event_type)
        status = st0
        created_at_raw = cast(datetime | None, existing.get("created_at"))
        created_at = self._ensure_timezone_aware(created_at_raw or datetime.now(timezone.utc))
        return IdempotencyResult(
            is_duplicate=True,
            status=status,
            result=existing.get("result"),
            error=cast(str | None, existing.get("error")),
            created_at=created_at,
            completed_at=cast(datetime | None, existing.get("completed_at")),
            processing_duration_ms=cast(int | None, existing.get("processing_duration_ms"))
        )

    async def _handle_processing_key(
            self,
            existing: dict[str, object],
            full_key: str,
            event_type: str,
    ) -> IdempotencyResult:
        created_at = self._ensure_timezone_aware(cast(datetime, existing["created_at"]))
        now = datetime.now(timezone.utc)

        if now - created_at > timedelta(seconds=self.config.processing_timeout_seconds):
            logger.warning(f"Idempotency key {full_key} processing timeout, allowing retry")
            await self._repo.update_set(full_key, {"created_at": now, "status": IdempotencyStatus.PROCESSING})
            return IdempotencyResult(is_duplicate=False, status=IdempotencyStatus.PROCESSING, created_at=now)

        self.metrics.record_idempotency_duplicate_blocked(event_type)
        return IdempotencyResult(is_duplicate=True, status=IdempotencyStatus.PROCESSING, created_at=created_at)

    async def _create_new_key(self, full_key: str, event: BaseEvent, ttl: int) -> IdempotencyResult:
        created_at = datetime.now(timezone.utc)
        try:
            await self._repo.insert_processing(
                key=full_key,
                event_type=event.event_type,
                event_id=str(event.event_id),
                created_at=created_at,
                ttl_seconds=ttl,
            )
            return IdempotencyResult(is_duplicate=False, status=IdempotencyStatus.PROCESSING, created_at=created_at)
        except DuplicateKeyError:
            # Race: someone inserted the same key concurrently — treat as existing
            existing = await self._repo.find_by_key(full_key)
            if existing:
                return await self._handle_existing_key(existing, full_key, event.event_type)
            # If for some reason it's still not found, allow processing
            return IdempotencyResult(is_duplicate=False, status=IdempotencyStatus.PROCESSING, created_at=created_at)

    def _ensure_timezone_aware(self, dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    async def _update_key_status(
            self,
            full_key: str,
            existing: dict[str, object],
            status: IdempotencyStatus,
            result: object | None = None,
            error: str | None = None,
    ) -> bool:
        created_at = self._ensure_timezone_aware(cast(datetime, existing["created_at"]))
        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - created_at).total_seconds() * 1000)

        update_fields: dict[str, object] = {
            "status": status,
            "completed_at": completed_at,
            "processing_duration_ms": duration_ms,
        }
        if error:
            update_fields["error"] = error
        if result is not None and self.config.enable_result_caching:
            result_json = json.dumps(result) if not isinstance(result, str) else result
            if len(result_json.encode()) <= self.config.max_result_size_bytes:
                update_fields["result"] = result
            else:
                logger.warning(f"Result too large to cache for key {full_key}")
        modified = await self._repo.update_set(full_key, update_fields)
        return modified > 0

    async def mark_completed(
            self,
            event: BaseEvent,
            result: object | None = None,
            key_strategy: str = "event_based",
            custom_key: str | None = None,
            fields: set[str] | None = None
    ) -> bool:
        full_key = self._generate_key(event, key_strategy, custom_key, fields)
        try:
            existing = await self._repo.find_by_key(full_key)
        except Exception as e:  # Narrow DB op
            logger.error(f"Failed to load idempotency key for completion: {e}")
            return False
        if not existing:
            logger.warning(f"Idempotency key {full_key} not found when marking completed")
            return False
        return await self._update_key_status(full_key, existing, IdempotencyStatus.COMPLETED, result=result)

    async def mark_failed(
            self,
            event: BaseEvent,
            error: str,
            key_strategy: str = "event_based",
            custom_key: str | None = None,
            fields: set[str] | None = None
    ) -> bool:
        full_key = self._generate_key(event, key_strategy, custom_key, fields)
        existing = await self._repo.find_by_key(full_key)
        if not existing:
            logger.warning(f"Idempotency key {full_key} not found when marking failed")
            return False
        return await self._update_key_status(full_key, existing, IdempotencyStatus.FAILED, error=error)

    async def remove(
            self,
            event: BaseEvent,
            key_strategy: str = "event_based",
            custom_key: str | None = None,
            fields: set[str] | None = None
    ) -> bool:
        full_key = self._generate_key(event, key_strategy, custom_key, fields)
        try:
            deleted = await self._repo.delete_key(full_key)
            return deleted > 0
        except Exception as e:
            logger.error(f"Failed to remove idempotency key: {e}")
            return False

    async def get_stats(self) -> dict[str, object]:
        counts_raw = await self._repo.aggregate_status_counts(self.config.key_prefix)
        status_counts = {
            IdempotencyStatus.PROCESSING: counts_raw.get(IdempotencyStatus.PROCESSING, 0),
            IdempotencyStatus.COMPLETED: counts_raw.get(IdempotencyStatus.COMPLETED, 0),
            IdempotencyStatus.FAILED: counts_raw.get(IdempotencyStatus.FAILED, 0),
        }
        return {"total_keys": sum(status_counts.values()),
                "status_counts": status_counts,
                "prefix": self.config.key_prefix}

    async def _update_stats_loop(self) -> None:
        while True:
            try:
                stats = await self.get_stats()
                from typing import cast
                total_keys = cast(int, stats.get("total_keys", 0))
                self.metrics.update_idempotency_keys_active(total_keys, self.config.key_prefix)
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Failed to update idempotency stats: {e}")
                await asyncio.sleep(300)


def create_idempotency_manager(
        database: AsyncIOMotorDatabase, config: IdempotencyConfig | None = None
) -> IdempotencyManager:
    if config is None:
        config = IdempotencyConfig()
    repository = IdempotencyRepository(database, collection_name=config.collection_name)
    return IdempotencyManager(config, repository)
