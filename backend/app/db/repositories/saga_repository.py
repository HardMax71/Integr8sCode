from datetime import datetime, timezone
from typing import Any

from beanie.odm.enums import SortDirection
from beanie.odm.operators.find import BaseFindOperator
from beanie.operators import GT, LT, In
from monggregate import Pipeline, S

from app.db.docs import ExecutionDocument, SagaDocument
from app.domain.enums.saga import SagaState
from app.domain.saga import Saga, SagaFilter, SagaListResult


class SagaRepository:
    def _filter_conditions(self, saga_filter: SagaFilter) -> list[BaseFindOperator]:
        """Build Beanie query conditions from SagaFilter."""
        conditions = [
            SagaDocument.state == saga_filter.state if saga_filter.state else None,
            In(SagaDocument.execution_id, saga_filter.execution_ids) if saga_filter.execution_ids else None,
            SagaDocument.context_data["user_id"] == saga_filter.user_id if saga_filter.user_id else None,
            SagaDocument.saga_name == saga_filter.saga_name if saga_filter.saga_name else None,
            GT(SagaDocument.created_at, saga_filter.created_after) if saga_filter.created_after else None,
            LT(SagaDocument.created_at, saga_filter.created_before) if saga_filter.created_before else None,
        ]
        if saga_filter.error_status is True:
            conditions.append(SagaDocument.error_message != None)  # noqa: E711
        elif saga_filter.error_status is False:
            conditions.append(SagaDocument.error_message == None)  # noqa: E711
        return [c for c in conditions if c is not None]

    async def upsert_saga(self, saga: Saga) -> bool:
        existing = await SagaDocument.find_one(SagaDocument.saga_id == saga.saga_id)
        doc = SagaDocument(**saga.model_dump())
        if existing:
            doc.id = existing.id
        await doc.save()
        return existing is not None

    async def get_saga_by_execution_and_name(self, execution_id: str, saga_name: str) -> Saga | None:
        doc = await SagaDocument.find_one(
            SagaDocument.execution_id == execution_id,
            SagaDocument.saga_name == saga_name,
        )
        return Saga.model_validate(doc, from_attributes=True) if doc else None

    async def get_saga(self, saga_id: str) -> Saga | None:
        doc = await SagaDocument.find_one(SagaDocument.saga_id == saga_id)
        return Saga.model_validate(doc, from_attributes=True) if doc else None

    async def get_sagas_by_execution(
            self, execution_id: str, state: SagaState | None = None, limit: int = 100, skip: int = 0
    ) -> SagaListResult:
        conditions = [
            SagaDocument.execution_id == execution_id,
            SagaDocument.state == state if state else None,
        ]
        conditions = [c for c in conditions if c is not None]

        query = SagaDocument.find(*conditions)
        total = await query.count()
        docs = await query.sort([("created_at", SortDirection.DESCENDING)]).skip(skip).limit(limit).to_list()
        return SagaListResult(
            sagas=[Saga.model_validate(d, from_attributes=True) for d in docs],
            total=total,
            skip=skip,
            limit=limit,
        )

    async def list_sagas(self, saga_filter: SagaFilter, limit: int = 100, skip: int = 0) -> SagaListResult:
        conditions = self._filter_conditions(saga_filter)
        query = SagaDocument.find(*conditions)
        total = await query.count()
        docs = await query.sort([("created_at", SortDirection.DESCENDING)]).skip(skip).limit(limit).to_list()
        return SagaListResult(
            sagas=[Saga.model_validate(d, from_attributes=True) for d in docs],
            total=total,
            skip=skip,
            limit=limit,
        )

    async def update_saga_state(self, saga_id: str, state: SagaState, error_message: str | None = None) -> bool:
        doc = await SagaDocument.find_one(SagaDocument.saga_id == saga_id)
        if not doc:
            return False

        doc.state = state
        doc.updated_at = datetime.now(timezone.utc)
        if error_message:
            doc.error_message = error_message
        await doc.save()
        return True

    async def get_user_execution_ids(self, user_id: str) -> list[str]:
        docs = await ExecutionDocument.find(ExecutionDocument.user_id == user_id).to_list()
        return [doc.execution_id for doc in docs]

    async def count_sagas_by_state(self) -> dict[str, int]:
        pipeline = Pipeline().group(by=SagaDocument.state, query={"count": S.sum(1)})
        result = {}
        async for doc in SagaDocument.aggregate(pipeline.export()):
            result[doc["_id"]] = doc["count"]
        return result

    async def find_timed_out_sagas(
            self,
            cutoff_time: datetime,
            states: list[SagaState] | None = None,
            limit: int = 100,
    ) -> list[Saga]:
        states = states or [SagaState.RUNNING, SagaState.COMPENSATING]
        docs = (
            await SagaDocument.find(
                In(SagaDocument.state, states),
                LT(SagaDocument.created_at, cutoff_time),
            )
            .limit(limit)
            .to_list()
        )
        return [Saga.model_validate(d, from_attributes=True) for d in docs]

    async def get_saga_statistics(self, saga_filter: SagaFilter | None = None) -> dict[str, Any]:
        conditions = self._filter_conditions(saga_filter) if saga_filter else []
        base_query = SagaDocument.find(*conditions)
        total = await base_query.count()

        # Group by state
        state_pipeline = Pipeline().group(by=SagaDocument.state, query={"count": S.sum(1)})
        states = {}
        async for doc in base_query.aggregate(state_pipeline.export()):
            states[doc["_id"]] = doc["count"]

        # Average duration for completed sagas
        completed_conditions = [
            *conditions,
            SagaDocument.state == SagaState.COMPLETED,
            SagaDocument.completed_at != None,  # noqa: E711
        ]
        duration_pipeline = (
            Pipeline()
            .project(
                duration={"$subtract": [S.field(SagaDocument.completed_at), S.field(SagaDocument.created_at)]}
            )
            .group(by=None, query={"avg_duration": S.avg("$duration")})
        )
        avg_duration = 0.0
        async for doc in SagaDocument.find(*completed_conditions).aggregate(duration_pipeline.export()):
            avg_duration = doc["avg_duration"] / 1000.0 if doc["avg_duration"] else 0.0

        return {"total": total, "by_state": states, "average_duration_seconds": avg_duration}
