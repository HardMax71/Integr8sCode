from datetime import datetime, timezone
from typing import Any, Dict

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.domain.enums.execution import ExecutionStatus
from app.domain.execution.models import DomainExecution, ResourceUsageDomain
from app.domain.sse.models import SSEEventDomain, SSEExecutionStatusDomain


class SSERepository:
    def __init__(self, database: AsyncIOMotorDatabase):
        self.db = database
        self.executions_collection: AsyncIOMotorCollection = self.db.get_collection("executions")
        self.events_collection: AsyncIOMotorCollection = self.db.get_collection("events")

    async def get_execution_status(self, execution_id: str) -> SSEExecutionStatusDomain | None:
        execution = await self.executions_collection.find_one(
            {"execution_id": execution_id},
            {"status": 1, "execution_id": 1, "_id": 0}
        )

        if execution:
            return SSEExecutionStatusDomain(
                execution_id=execution_id,
                status=str(execution.get("status", "unknown")),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        return None

    async def get_execution_events(
            self,
            execution_id: str,
            limit: int = 100,
            skip: int = 0
    ) -> list[SSEEventDomain]:
        cursor = self.events_collection.find(
            {"aggregate_id": execution_id}
        ).sort("timestamp", 1).skip(skip).limit(limit)

        events: list[SSEEventDomain] = []
        async for event in cursor:
            events.append(SSEEventDomain(
                aggregate_id=str(event.get("aggregate_id", "")),
                timestamp=event.get("timestamp"),
            ))
        return events

    async def get_execution_for_user(self, execution_id: str, user_id: str) -> DomainExecution | None:
        doc = await self.executions_collection.find_one({
            "execution_id": execution_id,
            "user_id": user_id
        })
        if not doc:
            return None
        return self._doc_to_execution(doc)

    async def get_execution(self, execution_id: str) -> DomainExecution | None:
        doc = await self.executions_collection.find_one({
            "execution_id": execution_id
        })
        if not doc:
            return None
        return self._doc_to_execution(doc)

    def _doc_to_execution(self, doc: Dict[str, Any]) -> DomainExecution:
        sv = doc.get("status")
        try:
            st = sv if isinstance(sv, ExecutionStatus) else ExecutionStatus(str(sv))
        except Exception:
            st = ExecutionStatus.QUEUED
        return DomainExecution(
            execution_id=str(doc.get("execution_id")),
            script=str(doc.get("script", "")),
            status=st,
            output=doc.get("output"),
            errors=doc.get("errors"),
            lang=str(doc.get("lang", "python")),
            lang_version=str(doc.get("lang_version", "3.11")),
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
            updated_at=doc.get("updated_at", datetime.now(timezone.utc)),
            resource_usage=ResourceUsageDomain.from_dict(doc.get("resource_usage") or {}),
            user_id=doc.get("user_id"),
            exit_code=doc.get("exit_code"),
            error_type=doc.get("error_type"),
        )
