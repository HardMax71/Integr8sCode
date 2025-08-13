import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Dict, Mapping, Optional, Sequence, Set

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pydantic import BaseModel
from pymongo import ASCENDING, IndexModel
from pymongo.errors import DuplicateKeyError

from app.core.logging import logger
from app.db.mongodb import DatabaseManager
from app.schemas_avro.event_schemas import BaseEvent
from app.services.idempotency.metrics import (
    IDEMPOTENCY_CACHE_HITS,
    IDEMPOTENCY_CACHE_MISSES,
    IDEMPOTENCY_DUPLICATES_BLOCKED,
    IDEMPOTENCY_KEYS_ACTIVE,
)


class IdempotencyStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class IdempotencyResult(BaseModel):
    is_duplicate: bool
    status: Optional[IdempotencyStatus] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    processing_duration_ms: Optional[int] = None


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
    def content_hash(event: BaseEvent, fields: Optional[Set[str]] = None) -> str:
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
    def __init__(self, config: IdempotencyConfig, db_manager: DatabaseManager) -> None:
        self.config = config
        self.db_manager = db_manager
        self._db: Optional[AsyncIOMotorDatabase] = None
        self._collection: Optional[AsyncIOMotorCollection] = None
        self._initialized = False
        self._lock_registry: Dict[str, asyncio.Lock] = {}
        self._stats_update_task: Optional[asyncio.Task[None]] = None

    async def initialize(self) -> None:
        if self._initialized:
            return

        try:
            self._db = self.db_manager.get_database()
            self._collection = self._db[self.config.collection_name]

            indexes = [
                IndexModel([("key", ASCENDING)], unique=True),
                IndexModel(
                    [("created_at", ASCENDING)],
                    expireAfterSeconds=self.config.default_ttl_seconds
                ),
                IndexModel([("status", ASCENDING)]),
                IndexModel([("event_type", ASCENDING)])
            ]
            await self._collection.create_indexes(indexes)

            self._initialized = True

            if self.config.enable_metrics:
                self._stats_update_task = asyncio.create_task(self._update_stats_loop())

            logger.info("Initialized MongoDB-based idempotency management")
        except Exception as e:
            logger.error(f"Failed to initialize idempotency collection: {e}")
            raise

    async def close(self) -> None:
        if self._stats_update_task:
            self._stats_update_task.cancel()
            try:
                await self._stats_update_task
            except asyncio.CancelledError:
                pass

        self._initialized = False
        logger.info("Closed idempotency manager")

    def _generate_key(
            self,
            event: BaseEvent,
            key_strategy: str,
            custom_key: Optional[str] = None,
            fields: Optional[Set[str]] = None
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
            custom_key: Optional[str] = None,
            ttl_seconds: Optional[int] = None,
            fields: Optional[Set[str]] = None
    ) -> IdempotencyResult:
        if not self._initialized:
            await self.initialize()

        full_key = self._generate_key(event, key_strategy, custom_key, fields)
        ttl = ttl_seconds or self.config.default_ttl_seconds

        try:
            if self._collection is None:
                raise ValueError("Collection not initialized")
                
            existing = await self._collection.find_one({"key": full_key})

            if existing:
                IDEMPOTENCY_CACHE_HITS.labels(
                    event_type=event.event_type,
                    operation="check_and_reserve"
                ).inc()

                return await self._handle_existing_key(existing, full_key, event.event_type)

            IDEMPOTENCY_CACHE_MISSES.labels(
                event_type=event.event_type,
                operation="check_and_reserve"
            ).inc()

            return await self._create_new_key(full_key, event, ttl, key_strategy, custom_key, ttl_seconds, fields)

        except Exception as e:
            logger.error(f"Failed to check idempotency key: {e}")
            return IdempotencyResult(is_duplicate=False)

    async def _handle_existing_key(
            self,
            existing: Dict[str, Any],
            full_key: str,
            event_type: str
    ) -> IdempotencyResult:
        if existing["status"] == IdempotencyStatus.PROCESSING:
            return await self._handle_processing_key(existing, full_key, event_type)

        IDEMPOTENCY_DUPLICATES_BLOCKED.labels(event_type=event_type).inc()

        return IdempotencyResult(
            is_duplicate=True,
            status=existing["status"],
            result=existing.get("result"),
            error=existing.get("error"),
            created_at=existing["created_at"],
            completed_at=existing.get("completed_at"),
            processing_duration_ms=existing.get("processing_duration_ms")
        )

    async def _handle_processing_key(
            self,
            existing: Dict[str, Any],
            full_key: str,
            event_type: str
    ) -> IdempotencyResult:
        created_at = self._ensure_timezone_aware(existing["created_at"])
        now = datetime.now(timezone.utc)

        if now - created_at > timedelta(seconds=self.config.processing_timeout_seconds):
            logger.warning(f"Idempotency key {full_key} processing timeout, allowing retry")
            if self._collection is None:
                raise ValueError("Collection not initialized")
                
            await self._collection.update_one(
                {"key": full_key},
                {"$set": {
                    "created_at": now,
                    "status": IdempotencyStatus.PROCESSING
                }}
            )
            return IdempotencyResult(
                is_duplicate=False,
                status=IdempotencyStatus.PROCESSING,
                created_at=now
            )

        IDEMPOTENCY_DUPLICATES_BLOCKED.labels(event_type=event_type).inc()
        return IdempotencyResult(
            is_duplicate=True,
            status=IdempotencyStatus.PROCESSING,
            created_at=created_at
        )

    async def _create_new_key(
            self,
            full_key: str,
            event: BaseEvent,
            ttl: int,
            key_strategy: str,
            custom_key: Optional[str],
            ttl_seconds: Optional[int],
            fields: Optional[Set[str]]
    ) -> IdempotencyResult:
        created_at = datetime.now(timezone.utc)
        doc = {
            "key": full_key,
            "status": IdempotencyStatus.PROCESSING,
            "event_type": event.event_type,
            "event_id": str(event.event_id),
            "created_at": created_at,
            "ttl_seconds": ttl
        }

        try:
            if self._collection is None:
                raise ValueError("Collection not initialized")
                
            await self._collection.insert_one(doc)
            return IdempotencyResult(
                is_duplicate=False,
                status=IdempotencyStatus.PROCESSING,
                created_at=created_at
            )
        except DuplicateKeyError:
            return await self.check_and_reserve(event, key_strategy, custom_key, ttl_seconds, fields)

    def _ensure_timezone_aware(self, dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    async def _update_key_status(
            self,
            full_key: str,
            existing: Dict[str, Any],
            status: IdempotencyStatus,
            result: Optional[Any] = None,
            error: Optional[str] = None
    ) -> bool:
        created_at = self._ensure_timezone_aware(existing["created_at"])
        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - created_at).total_seconds() * 1000)

        update_doc = {
            "$set": {
                "status": status,
                "completed_at": completed_at,
                "processing_duration_ms": duration_ms
            }
        }

        if error:
            update_doc["$set"]["error"] = error

        if result is not None and self.config.enable_result_caching:
            result_json = json.dumps(result) if not isinstance(result, str) else result
            if len(result_json.encode()) <= self.config.max_result_size_bytes:
                update_doc["$set"]["result"] = result
            else:
                logger.warning(f"Result too large to cache for key {full_key}")

        if not self._collection:
            raise ValueError("Collection not initialized")
            
        update_result = await self._collection.update_one({"key": full_key}, update_doc)
        return update_result.modified_count > 0

    async def mark_completed(
            self,
            event: BaseEvent,
            result: Optional[Any] = None,
            key_strategy: str = "event_based",
            custom_key: Optional[str] = None,
            fields: Optional[Set[str]] = None
    ) -> bool:
        if not self._initialized:
            await self.initialize()

        full_key = self._generate_key(event, key_strategy, custom_key, fields)

        try:
            if self._collection is None:
                raise ValueError("Collection not initialized")
                
            existing = await self._collection.find_one({"key": full_key})
            if not existing:
                logger.warning(f"Idempotency key {full_key} not found when marking completed")
                return False

            return await self._update_key_status(
                full_key,
                existing,
                IdempotencyStatus.COMPLETED,
                result=result
            )

        except Exception as e:
            logger.error(f"Failed to mark idempotency key completed: {e}")
            return False

    async def mark_failed(
            self,
            event: BaseEvent,
            error: str,
            key_strategy: str = "event_based",
            custom_key: Optional[str] = None,
            fields: Optional[Set[str]] = None
    ) -> bool:
        if not self._initialized:
            await self.initialize()

        full_key = self._generate_key(event, key_strategy, custom_key, fields)

        try:
            if self._collection is None:
                raise ValueError("Collection not initialized")
                
            existing = await self._collection.find_one({"key": full_key})
            if not existing:
                logger.warning(f"Idempotency key {full_key} not found when marking failed")
                return False

            return await self._update_key_status(
                full_key,
                existing,
                IdempotencyStatus.FAILED,
                error=error
            )

        except Exception as e:
            logger.error(f"Failed to mark idempotency key failed: {e}")
            return False

    async def remove(
            self,
            event: BaseEvent,
            key_strategy: str = "event_based",
            custom_key: Optional[str] = None,
            fields: Optional[Set[str]] = None
    ) -> bool:
        if not self._initialized:
            await self.initialize()

        full_key = self._generate_key(event, key_strategy, custom_key, fields)

        try:
            if self._collection is None:
                raise ValueError("Collection not initialized")
                
            result = await self._collection.delete_one({"key": full_key})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Failed to remove idempotency key: {e}")
            return False

    async def get_stats(self) -> Dict[str, Any]:
        if not self._initialized:
            return {}

        try:
            pipeline: Sequence[Mapping[str, Any]] = [
                {"$match": {"key": {"$regex": f"^{self.config.key_prefix}:"}}},
                {"$group": {
                    "_id": "$status",
                    "count": {"$sum": 1}
                }}
            ]

            status_counts = {
                IdempotencyStatus.PROCESSING: 0,
                IdempotencyStatus.COMPLETED: 0,
                IdempotencyStatus.FAILED: 0
            }

            if self._collection is None:
                raise ValueError("Collection not initialized")
                
            async for doc in self._collection.aggregate(pipeline):
                if doc["_id"] in status_counts:
                    status_counts[doc["_id"]] = doc["count"]

            return {
                "total_keys": sum(status_counts.values()),
                "status_counts": status_counts,
                "prefix": self.config.key_prefix
            }
        except Exception as e:
            logger.error(f"Failed to get idempotency stats: {e}")
            return {}

    async def health_check(self) -> Dict[str, Any]:
        try:
            if self._collection is None:
                raise ValueError("Collection not initialized")
                
            await self._collection.find_one({}, {"_id": 1})
            stats = await self.get_stats()

            return {
                "healthy": True,
                "stats": stats
            }
        except Exception as e:
            logger.error(f"Idempotency health check failed: {e}")
            return {
                "healthy": False,
                "error": str(e)
            }

    async def _update_stats_loop(self) -> None:
        while True:
            try:
                stats = await self.get_stats()
                IDEMPOTENCY_KEYS_ACTIVE.labels(
                    prefix=self.config.key_prefix
                ).set(stats.get("total_keys", 0))

                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Failed to update idempotency stats: {e}")
                await asyncio.sleep(300)


class IdempotencyManagerSingleton:
    _instance: Optional[IdempotencyManager] = None

    @classmethod
    async def get_instance(
            cls,
            db_manager: Optional[DatabaseManager] = None
    ) -> IdempotencyManager:
        if cls._instance is None:
            if db_manager is None:
                raise ValueError("db_manager must be provided for first initialization")
            config = IdempotencyConfig()
            cls._instance = IdempotencyManager(config, db_manager)
            await cls._instance.initialize()
        return cls._instance

    @classmethod
    async def close_instance(cls) -> None:
        if cls._instance:
            await cls._instance.close()
            cls._instance = None


def get_idempotency_manager() -> Optional[IdempotencyManager]:
    return IdempotencyManagerSingleton._instance


async def close_idempotency_manager() -> None:
    await IdempotencyManagerSingleton.close_instance()
