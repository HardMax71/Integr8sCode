from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from app.core.logging import logger
from app.domain.enums.events import EventType
from app.domain.enums.replay import ReplayStatus
from app.domain.replay.models import ReplayConfig, ReplayFilter, ReplaySessionState


class ReplayRepository:
    def __init__(self, database: AsyncIOMotorDatabase) -> None:
        self.db = database

    async def create_indexes(self) -> None:
        try:
            # Replay sessions indexes
            collection = self.db.replay_sessions
            await collection.create_index([("session_id", ASCENDING)], unique=True)
            await collection.create_index([("status", ASCENDING)])
            await collection.create_index([("created_at", DESCENDING)])
            await collection.create_index([("user_id", ASCENDING)])
            
            # Events collection indexes for replay queries
            events_collection = self.db.events
            await events_collection.create_index([("execution_id", 1), ("timestamp", 1)])
            await events_collection.create_index([("event_type", 1), ("timestamp", 1)])
            await events_collection.create_index([("metadata.user_id", 1), ("timestamp", 1)])
            
            logger.info("Replay repository indexes created successfully")
        except Exception as e:
            logger.error(f"Error creating replay repository indexes: {e}")
            raise

    async def save_session(self, session: ReplaySessionState) -> None:
        """Save or update a replay session (domain → persistence)."""
        doc = self._session_state_to_doc(session)
        await self.db.replay_sessions.update_one(
            {"session_id": session.session_id},
            {"$set": doc},
            upsert=True
        )

    async def get_session(self, session_id: str) -> ReplaySessionState | None:
        """Get a replay session by ID (persistence → domain)."""
        data = await self.db.replay_sessions.find_one({"session_id": session_id})
        return self._doc_to_session_state(data) if data else None

    async def list_sessions(
            self,
            status: str | None = None,
            user_id: str | None = None,
            limit: int = 100,
            skip: int = 0
    ) -> list[ReplaySessionState]:
        collection = self.db.replay_sessions

        query = {}
        if status:
            query["status"] = status
        if user_id:
            query["config.filter.user_id"] = user_id

        cursor = collection.find(query).sort("created_at", DESCENDING).skip(skip).limit(limit)
        sessions: list[ReplaySessionState] = []
        async for doc in cursor:
            state = self._doc_to_session_state(doc)
            if state:
                sessions.append(state)
        return sessions

    async def update_session_status(self, session_id: str, status: str) -> bool:
        """Update the status of a replay session"""
        result = await self.db.replay_sessions.update_one(
            {"session_id": session_id},
            {"$set": {"status": status}}
        )
        return result.modified_count > 0

    async def delete_old_sessions(self, cutoff_time: str) -> int:
        """Delete old completed/failed/cancelled sessions"""
        result = await self.db.replay_sessions.delete_many({
            "created_at": {"$lt": cutoff_time},
            "status": {"$in": ["completed", "failed", "cancelled"]}
        })
        return result.deleted_count

    async def count_sessions(self, query: dict[str, object] | None = None) -> int:
        """Count sessions matching the given query"""
        return await self.db.replay_sessions.count_documents(query or {})
    
    async def update_replay_session(
            self,
            session_id: str,
            updates: Dict[str, Any]
    ) -> bool:
        """Update specific fields of a replay session"""
        result = await self.db.replay_sessions.update_one(
            {"session_id": session_id},
            {"$set": updates}
        )
        return result.modified_count > 0

    def _session_state_to_doc(self, s: ReplaySessionState) -> Dict[str, Any]:
        """Serialize domain session state to a MongoDB document."""
        cfg = s.config
        flt = cfg.filter
        return {
            "session_id": s.session_id,
            "status": s.status,
            "total_events": s.total_events,
            "replayed_events": s.replayed_events,
            "failed_events": s.failed_events,
            "skipped_events": s.skipped_events,
            "created_at": s.created_at,
            "started_at": s.started_at,
            "completed_at": s.completed_at,
            "last_event_at": s.last_event_at,
            "errors": s.errors,
            "config": {
                "replay_type": cfg.replay_type,
                "target": cfg.target,
                "speed_multiplier": cfg.speed_multiplier,
                "preserve_timestamps": cfg.preserve_timestamps,
                "batch_size": cfg.batch_size,
                "max_events": cfg.max_events,
                "skip_errors": cfg.skip_errors,
                "retry_failed": cfg.retry_failed,
                "retry_attempts": cfg.retry_attempts,
                "target_file_path": cfg.target_file_path,
                "target_topics": {k: v for k, v in (cfg.target_topics or {}).items()},
                "filter": {
                    "execution_id": flt.execution_id,
                    "event_types": flt.event_types if flt.event_types else None,
                    "exclude_event_types": flt.exclude_event_types if flt.exclude_event_types else None,
                    "start_time": flt.start_time,
                    "end_time": flt.end_time,
                    "user_id": flt.user_id,
                    "service_name": flt.service_name,
                    "custom_query": flt.custom_query,
                },
            },
        }

    def _doc_to_session_state(self, doc: Dict[str, Any]) -> ReplaySessionState | None:
        try:
            cfg_dict = doc.get("config", {})
            flt_dict = cfg_dict.get("filter", {})

            # Rehydrate domain filter/config
            event_types = [EventType(et) for et in flt_dict.get("event_types", [])] \
                if flt_dict.get("event_types") else None
            exclude_event_types = [EventType(et) for et in flt_dict.get("exclude_event_types", [])] \
                if flt_dict.get("exclude_event_types") else None
            flt = ReplayFilter(
                execution_id=flt_dict.get("execution_id"),
                event_types=event_types,
                start_time=flt_dict.get("start_time"),
                end_time=flt_dict.get("end_time"),
                user_id=flt_dict.get("user_id"),
                service_name=flt_dict.get("service_name"),
                custom_query=flt_dict.get("custom_query"),
                exclude_event_types=exclude_event_types,
            )
            cfg = ReplayConfig(
                replay_type=cfg_dict.get("replay_type"),
                target=cfg_dict.get("target"),
                filter=flt,
                speed_multiplier=cfg_dict.get("speed_multiplier", 1.0),
                preserve_timestamps=cfg_dict.get("preserve_timestamps", False),
                batch_size=cfg_dict.get("batch_size", 100),
                max_events=cfg_dict.get("max_events"),
                target_topics=None,  # string-keyed map not used by domain; optional override remains None
                target_file_path=cfg_dict.get("target_file_path"),
                skip_errors=cfg_dict.get("skip_errors", True),
                retry_failed=cfg_dict.get("retry_failed", False),
                retry_attempts=cfg_dict.get("retry_attempts", 3),
                enable_progress_tracking=cfg_dict.get("enable_progress_tracking", True),
            )
            status_str = doc.get("status", ReplayStatus.CREATED)
            status = status_str if isinstance(status_str, ReplayStatus) else ReplayStatus(str(status_str))
            return ReplaySessionState(
                session_id=doc.get("session_id", ""),
                config=cfg,
                status=status,
                total_events=doc.get("total_events", 0),
                replayed_events=doc.get("replayed_events", 0),
                failed_events=doc.get("failed_events", 0),
                skipped_events=doc.get("skipped_events", 0),
                created_at=doc.get("created_at", datetime.now(timezone.utc)),
                started_at=doc.get("started_at"),
                completed_at=doc.get("completed_at"),
                last_event_at=doc.get("last_event_at"),
                errors=doc.get("errors", []),
            )
        except Exception as e:
            logger.error(f"Failed to deserialize replay session document: {e}")
            return None
    
    async def count_events(self, filter: ReplayFilter) -> int:
        """Count events matching the given filter"""
        query = filter.to_mongo_query()
        return await self.db.events.count_documents(query)
    
    async def fetch_events(
            self,
            filter: ReplayFilter,
            batch_size: int = 100,
            skip: int = 0
    ) -> AsyncIterator[List[Dict[str, Any]]]:
        """Fetch events in batches based on filter"""
        query = filter.to_mongo_query()
        cursor = self.db.events.find(query).sort("timestamp", 1).skip(skip)
        
        batch = []
        async for doc in cursor:
            batch.append(doc)
            if len(batch) >= batch_size:
                yield batch
                batch = []
        
        if batch:
            yield batch
