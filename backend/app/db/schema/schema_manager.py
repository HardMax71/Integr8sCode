from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable, Iterable

from pymongo import ASCENDING, DESCENDING, IndexModel

from app.core.database_context import Database
from app.core.logging import logger
from app.domain.events.event_models import EventFields


class SchemaManager:
    """Applies idempotent, versioned MongoDB migrations per database."""

    def __init__(self, database: Database) -> None:
        self.db = database
        self._versions = self.db["schema_versions"]

    async def _is_applied(self, migration_id: str) -> bool:
        doc = await self._versions.find_one({"_id": migration_id})
        return doc is not None

    async def _mark_applied(self, migration_id: str, description: str) -> None:
        await self._versions.update_one(
            {"_id": migration_id},
            {
                "$set": {
                    "description": description,
                    "applied_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )

    async def apply_all(self) -> None:
        """Apply all pending migrations in order."""
        migrations: list[tuple[str, str, Callable[[], Awaitable[None]]]] = [
            ("0001_events_init", "Create events indexes and validator", self._m_0001_events_init),
            ("0002_user_settings_indexes", "Create user settings indexes", self._m_0002_user_settings),
            ("0003_replay_indexes", "Create replay indexes", self._m_0003_replay),
            ("0004_notification_indexes", "Create notification indexes", self._m_0004_notifications),
            ("0005_idempotency_indexes", "Create idempotency indexes", self._m_0005_idempotency),
            ("0006_saga_indexes", "Create saga indexes", self._m_0006_sagas),
            ("0007_execution_results_indexes", "Create execution results indexes", self._m_0007_execution_results),
            ("0008_dlq_indexes", "Create DLQ indexes", self._m_0008_dlq),
            (
                "0009_event_store_extra_indexes",
                "Additional events indexes for event_store",
                self._m_0009_event_store_extra,
            ),
        ]

        for mig_id, desc, func in migrations:
            if await self._is_applied(mig_id):
                continue
            logger.info(f"Applying migration {mig_id}: {desc}")
            await func()
            await self._mark_applied(mig_id, desc)
            logger.info(f"Migration {mig_id} applied")

    async def _m_0001_events_init(self) -> None:
        events = self.db["events"]

        # Create named, idempotent indexes
        indexes: Iterable[IndexModel] = [
            IndexModel([(EventFields.EVENT_ID, ASCENDING)], name="idx_event_id_unique", unique=True),
            IndexModel(
                [(EventFields.EVENT_TYPE, ASCENDING), (EventFields.TIMESTAMP, DESCENDING)], name="idx_event_type_ts"
            ),
            IndexModel(
                [(EventFields.AGGREGATE_ID, ASCENDING), (EventFields.TIMESTAMP, DESCENDING)], name="idx_aggregate_ts"
            ),
            IndexModel([(EventFields.METADATA_CORRELATION_ID, ASCENDING)], name="idx_meta_correlation"),
            IndexModel(
                [(EventFields.METADATA_USER_ID, ASCENDING), (EventFields.TIMESTAMP, DESCENDING)],
                name="idx_meta_user_ts",
            ),
            IndexModel(
                [(EventFields.METADATA_SERVICE_NAME, ASCENDING), (EventFields.TIMESTAMP, DESCENDING)],
                name="idx_meta_service_ts",
            ),
            IndexModel([(EventFields.STATUS, ASCENDING), (EventFields.TIMESTAMP, DESCENDING)], name="idx_status_ts"),
            IndexModel([(EventFields.PAYLOAD_EXECUTION_ID, ASCENDING)], name="idx_payload_execution", sparse=True),
            IndexModel([(EventFields.PAYLOAD_POD_NAME, ASCENDING)], name="idx_payload_pod", sparse=True),
            # Optional TTL on ttl_expires_at (no effect for nulls)
            IndexModel([(EventFields.TTL_EXPIRES_AT, ASCENDING)], name="idx_ttl", expireAfterSeconds=0),
            # Text search index to support $text queries
            # Use language_override: "none" to prevent MongoDB from interpreting
            # the "language" field as a text search language (which causes
            # "language override unsupported: python" errors)
            IndexModel(
                [
                    (EventFields.EVENT_TYPE, "text"),
                    (EventFields.METADATA_SERVICE_NAME, "text"),
                    (EventFields.METADATA_USER_ID, "text"),
                    (EventFields.PAYLOAD, "text"),
                ],
                name="idx_text_search",
                language_override="none",
                default_language="english",
            ),
        ]

        try:
            await events.create_indexes(list(indexes))
            logger.info("Events indexes ensured")
        except Exception as e:
            logger.warning(f"Failed ensuring events indexes: {e}")

        # Validator (moderate, warn) — non-blocking
        try:
            await self.db.command(
                {
                    "collMod": "events",
                    "validator": {"$jsonSchema": self._event_json_schema()},
                    "validationLevel": "moderate",
                    "validationAction": "warn",
                }
            )
            logger.info("Events collection validator ensured")
        except Exception as e:
            logger.warning(f"Could not set events validator: {e}")

    @staticmethod
    def _event_json_schema() -> dict:
        return {
            "bsonType": "object",
            "required": [
                EventFields.EVENT_ID,
                EventFields.EVENT_TYPE,
                EventFields.TIMESTAMP,
                EventFields.EVENT_VERSION,
            ],
            "properties": {
                EventFields.EVENT_ID: {"bsonType": "string"},
                EventFields.EVENT_TYPE: {"bsonType": "string"},
                EventFields.TIMESTAMP: {"bsonType": "date"},
                EventFields.EVENT_VERSION: {"bsonType": "string", "pattern": "^\\d+\\.\\d+$"},
                EventFields.AGGREGATE_ID: {"bsonType": ["string", "null"]},
                EventFields.METADATA: {"bsonType": "object"},
                EventFields.PAYLOAD: {"bsonType": "object"},
                EventFields.STORED_AT: {"bsonType": ["date", "null"]},
                EventFields.TTL_EXPIRES_AT: {"bsonType": ["date", "null"]},
                EventFields.STATUS: {"bsonType": ["string", "null"]},
            },
        }

    async def _m_0002_user_settings(self) -> None:
        snapshots = self.db["user_settings_snapshots"]
        events = self.db["events"]
        try:
            await snapshots.create_indexes(
                [
                    IndexModel([("user_id", ASCENDING)], name="idx_settings_user_unique", unique=True),
                    IndexModel([("updated_at", DESCENDING)], name="idx_settings_updated_at_desc"),
                ]
            )
            await events.create_indexes(
                [
                    IndexModel([("event_type", ASCENDING), ("aggregate_id", ASCENDING)], name="idx_events_type_agg"),
                    IndexModel([("aggregate_id", ASCENDING), ("timestamp", ASCENDING)], name="idx_events_agg_ts"),
                ]
            )
            logger.info("User settings indexes ensured")
        except Exception as e:
            logger.warning(f"Failed ensuring user settings indexes: {e}")

    async def _m_0003_replay(self) -> None:
        sessions = self.db["replay_sessions"]
        events = self.db["events"]
        try:
            await sessions.create_indexes(
                [
                    IndexModel([("session_id", ASCENDING)], name="idx_replay_session_id", unique=True),
                    IndexModel([("status", ASCENDING)], name="idx_replay_status"),
                    IndexModel([("created_at", DESCENDING)], name="idx_replay_created_at_desc"),
                    IndexModel([("user_id", ASCENDING)], name="idx_replay_user"),
                ]
            )
            await events.create_indexes(
                [
                    IndexModel([("execution_id", ASCENDING), ("timestamp", ASCENDING)], name="idx_events_exec_ts"),
                    IndexModel([("event_type", ASCENDING), ("timestamp", ASCENDING)], name="idx_events_type_ts"),
                    IndexModel([("metadata.user_id", ASCENDING), ("timestamp", ASCENDING)], name="idx_events_user_ts"),
                ]
            )
            logger.info("Replay indexes ensured")
        except Exception as e:
            logger.warning(f"Failed ensuring replay indexes: {e}")

    async def _m_0004_notifications(self) -> None:
        notifications = self.db["notifications"]
        rules = self.db["notification_rules"]
        subs = self.db["notification_subscriptions"]
        try:
            await notifications.create_indexes(
                [
                    IndexModel(
                        [("user_id", ASCENDING), ("created_at", DESCENDING)], name="idx_notif_user_created_desc"
                    ),
                    IndexModel([("status", ASCENDING), ("scheduled_for", ASCENDING)], name="idx_notif_status_sched"),
                    IndexModel([("created_at", ASCENDING)], name="idx_notif_created_at"),
                    IndexModel([("notification_id", ASCENDING)], name="idx_notif_id_unique", unique=True),
                ]
            )
            await rules.create_indexes(
                [
                    IndexModel([("event_types", ASCENDING)], name="idx_rules_event_types"),
                    IndexModel([("enabled", ASCENDING)], name="idx_rules_enabled"),
                ]
            )
            await subs.create_indexes(
                [
                    IndexModel(
                        [("user_id", ASCENDING), ("channel", ASCENDING)],
                        name="idx_sub_user_channel_unique",
                        unique=True,
                    ),
                    IndexModel([("enabled", ASCENDING)], name="idx_sub_enabled"),
                ]
            )
            logger.info("Notification indexes ensured")
        except Exception as e:
            logger.warning(f"Failed ensuring notification indexes: {e}")

    async def _m_0005_idempotency(self) -> None:
        coll = self.db["idempotency_keys"]
        try:
            await coll.create_indexes(
                [
                    IndexModel([("key", ASCENDING)], name="idx_idem_key_unique", unique=True),
                    IndexModel([("created_at", ASCENDING)], name="idx_idem_created_ttl", expireAfterSeconds=3600),
                    IndexModel([("status", ASCENDING)], name="idx_idem_status"),
                    IndexModel([("event_type", ASCENDING)], name="idx_idem_event_type"),
                ]
            )
            logger.info("Idempotency indexes ensured")
        except Exception as e:
            logger.warning(f"Failed ensuring idempotency indexes: {e}")

    async def _m_0006_sagas(self) -> None:
        coll = self.db["sagas"]
        try:
            await coll.create_indexes(
                [
                    IndexModel([("saga_id", ASCENDING)], name="idx_saga_id_unique", unique=True),
                    IndexModel([("execution_id", ASCENDING)], name="idx_saga_execution"),
                    IndexModel([("state", ASCENDING)], name="idx_saga_state"),
                    IndexModel([("created_at", ASCENDING)], name="idx_saga_created_at"),
                    IndexModel([("state", ASCENDING), ("created_at", ASCENDING)], name="idx_saga_state_created"),
                ]
            )
            logger.info("Saga indexes ensured")
        except Exception as e:
            logger.warning(f"Failed ensuring saga indexes: {e}")

    async def _m_0007_execution_results(self) -> None:
        coll = self.db["execution_results"]
        try:
            await coll.create_indexes(
                [
                    IndexModel([("execution_id", ASCENDING)], name="idx_results_execution_unique", unique=True),
                    IndexModel([("created_at", ASCENDING)], name="idx_results_created_at"),
                    IndexModel(
                        [("user_id", ASCENDING), ("created_at", DESCENDING)], name="idx_results_user_created_desc"
                    ),
                ]
            )
            logger.info("Execution results indexes ensured")
        except Exception as e:
            logger.warning(f"Failed ensuring execution results indexes: {e}")

    async def _m_0008_dlq(self) -> None:
        coll = self.db["dlq_messages"]
        try:
            await coll.create_indexes(
                [
                    IndexModel([("event_id", ASCENDING)], name="idx_dlq_event_id_unique", unique=True),
                    IndexModel([("original_topic", ASCENDING)], name="idx_dlq_topic"),
                    IndexModel([("event_type", ASCENDING)], name="idx_dlq_event_type"),
                    IndexModel([("failed_at", DESCENDING)], name="idx_dlq_failed_desc"),
                    IndexModel([("retry_count", ASCENDING)], name="idx_dlq_retry_count"),
                    IndexModel([("status", ASCENDING)], name="idx_dlq_status"),
                    IndexModel([("next_retry_at", ASCENDING)], name="idx_dlq_next_retry"),
                    IndexModel(
                        [("created_at", ASCENDING)], name="idx_dlq_created_ttl", expireAfterSeconds=7 * 24 * 3600
                    ),
                ]
            )
            logger.info("DLQ indexes ensured")
        except Exception as e:
            logger.warning(f"Failed ensuring DLQ indexes: {e}")

    async def _m_0009_event_store_extra(self) -> None:
        events = self.db["events"]
        try:
            await events.create_indexes(
                [
                    IndexModel(
                        [("metadata.user_id", ASCENDING), ("event_type", ASCENDING)], name="idx_events_user_type"
                    ),
                    IndexModel(
                        [("event_type", ASCENDING), ("metadata.user_id", ASCENDING), ("timestamp", DESCENDING)],
                        name="idx_events_type_user_ts",
                    ),
                ]
            )
            logger.info("Additional event store indexes ensured")
        except Exception as e:
            logger.warning(f"Failed ensuring event store extra indexes: {e}")
