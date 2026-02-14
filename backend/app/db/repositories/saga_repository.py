import dataclasses
from datetime import datetime
from typing import Any

from beanie.odm.enums import SortDirection
from beanie.odm.operators.find import BaseFindOperator
from beanie.odm.queries.update import UpdateResponse
from beanie.operators import GT, LT, NE, Eq, In
from monggregate import Pipeline, S

from app.db.docs import ExecutionDocument, SagaDocument
from app.domain.enums import SagaState
from app.domain.saga import Saga, SagaContextData, SagaFilter, SagaListResult

_saga_fields = set(Saga.__dataclass_fields__)


class SagaRepository:
    @staticmethod
    def _to_domain(doc: SagaDocument) -> Saga:
        data = doc.model_dump(include=_saga_fields)
        data["context_data"] = SagaContextData(**data.get("context_data", {}))
        return Saga(**data)

    def _filter_conditions(self, saga_filter: SagaFilter) -> list[BaseFindOperator]:
        """Build Beanie query conditions from SagaFilter."""
        conditions: list[BaseFindOperator] = []
        if saga_filter.state:
            conditions.append(Eq(SagaDocument.state, saga_filter.state))
        if saga_filter.execution_ids:
            conditions.append(In(SagaDocument.execution_id, saga_filter.execution_ids))
        if saga_filter.user_id:
            conditions.append(Eq(SagaDocument.context_data.user_id, saga_filter.user_id))
        if saga_filter.saga_name:
            conditions.append(Eq(SagaDocument.saga_name, saga_filter.saga_name))
        if saga_filter.created_after:
            conditions.append(GT(SagaDocument.created_at, saga_filter.created_after))
        if saga_filter.created_before:
            conditions.append(LT(SagaDocument.created_at, saga_filter.created_before))
        if saga_filter.error_status is True:
            conditions.append(NE(SagaDocument.error_message, None))
        elif saga_filter.error_status is False:
            conditions.append(Eq(SagaDocument.error_message, None))
        return conditions

    async def upsert_saga(self, saga: Saga) -> bool:
        existing = await SagaDocument.find_one(SagaDocument.saga_id == saga.saga_id)
        doc = SagaDocument(**dataclasses.asdict(saga))
        if existing:
            doc.id = existing.id
        await doc.save()
        return existing is not None

    async def get_or_create_saga(self, saga: Saga) -> tuple[Saga, bool]:
        """Atomically get or create a saga by (execution_id, saga_name).

        Uses MongoDB findOneAndUpdate with $setOnInsert + upsert in a single
        atomic round-trip.  Returns (saga, created).
        """
        insert_doc = SagaDocument(**dataclasses.asdict(saga))
        insert_data = insert_doc.model_dump()
        insert_data.pop("id", None)
        insert_data.pop("revision_id", None)

        doc = await SagaDocument.find_one(
            SagaDocument.execution_id == saga.execution_id,
            SagaDocument.saga_name == saga.saga_name,
        ).upsert(
            {"$setOnInsert": insert_data},
            on_insert=insert_doc,
            response_type=UpdateResponse.NEW_DOCUMENT,
            upsert=True,
        )
        assert doc is not None
        created = doc.saga_id == saga.saga_id
        return self._to_domain(doc), created

    async def get_saga_by_execution_and_name(self, execution_id: str, saga_name: str) -> Saga | None:
        doc = await SagaDocument.find_one(
            SagaDocument.execution_id == execution_id,
            SagaDocument.saga_name == saga_name,
        )
        return self._to_domain(doc) if doc else None

    async def get_saga(self, saga_id: str) -> Saga | None:
        doc = await SagaDocument.find_one(SagaDocument.saga_id == saga_id)
        return self._to_domain(doc) if doc else None

    async def get_sagas_by_execution(
            self, execution_id: str, state: SagaState | None = None, limit: int = 100, skip: int = 0
    ) -> SagaListResult:
        conditions: list[BaseFindOperator] = [Eq(SagaDocument.execution_id, execution_id)]
        if state:
            conditions.append(Eq(SagaDocument.state, state))

        query = SagaDocument.find(*conditions)
        total = await query.count()
        docs = await query.sort([("created_at", SortDirection.DESCENDING)]).skip(skip).limit(limit).to_list()
        return SagaListResult(
            sagas=[self._to_domain(d) for d in docs],
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
            sagas=[self._to_domain(d) for d in docs],
            total=total,
            skip=skip,
            limit=limit,
        )

    async def get_user_execution_ids(self, user_id: str) -> list[str]:
        docs = await ExecutionDocument.find(ExecutionDocument.user_id == user_id).to_list()
        return [doc.execution_id for doc in docs]

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
        return [self._to_domain(d) for d in docs]

    async def get_saga_statistics(self, saga_filter: SagaFilter | None = None) -> dict[str, Any]:
        conditions = self._filter_conditions(saga_filter) if saga_filter else []
        base_query = SagaDocument.find(*conditions)
        total = await base_query.count()

        # Group by state
        state_pipeline = Pipeline().group(by=S.field(SagaDocument.state), query={"count": S.sum(1)})
        states = {}
        async for doc in base_query.aggregate(state_pipeline.export()):
            states[doc["_id"]] = doc["count"]

        # Average duration for completed sagas
        completed_conditions: list[BaseFindOperator] = [
            *conditions,
            Eq(SagaDocument.state, SagaState.COMPLETED),
            NE(SagaDocument.completed_at, None),
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
