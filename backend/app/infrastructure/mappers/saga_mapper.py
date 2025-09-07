from typing import Any, List

from app.domain.enums.saga import SagaState
from app.domain.saga.models import Saga, SagaFilter, SagaInstance
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.kafka.events.saga import SagaCancelledEvent
from app.schemas_pydantic.saga import SagaStatusResponse


class SagaMapper:
    """Maps between saga domain models and persistence representations."""

    def from_mongo(self, doc: dict[str, Any]) -> Saga:
        """Convert MongoDB document to domain model."""
        return Saga(
            saga_id=doc["saga_id"],
            saga_name=doc["saga_name"],
            execution_id=doc["execution_id"],
            state=SagaState(doc["state"]),
            current_step=doc.get("current_step"),
            completed_steps=doc.get("completed_steps", []),
            compensated_steps=doc.get("compensated_steps", []),
            context_data=doc.get("context_data", {}),
            error_message=doc.get("error_message"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
            completed_at=doc.get("completed_at"),
            retry_count=doc.get("retry_count", 0)
        )

    def to_mongo(self, saga: Saga) -> dict[str, Any]:
        """Convert domain model to MongoDB document.

        Assumes context_data is already sanitized at the source. As a light
        guardrail, exclude private keys (prefixed with "_") if any slip in.
        """
        context = saga.context_data or {}
        if isinstance(context, dict):
            context = {k: v for k, v in context.items() if not (isinstance(k, str) and k.startswith("_"))}

        return {
            "saga_id": saga.saga_id,
            "saga_name": saga.saga_name,
            "execution_id": saga.execution_id,
            "state": saga.state.value,
            "current_step": saga.current_step,
            "completed_steps": saga.completed_steps,
            "compensated_steps": saga.compensated_steps,
            "context_data": context,
            "error_message": saga.error_message,
            "created_at": saga.created_at,
            "updated_at": saga.updated_at,
            "completed_at": saga.completed_at,
            "retry_count": saga.retry_count
        }

    def from_instance(self, instance: SagaInstance) -> Saga:
        """Convert a SagaInstance (live orchestrator view) to Saga domain model."""
        return Saga(
            saga_id=instance.saga_id,
            saga_name=instance.saga_name,
            execution_id=instance.execution_id,
            state=instance.state,
            current_step=instance.current_step,
            completed_steps=instance.completed_steps,
            compensated_steps=instance.compensated_steps,
            context_data=instance.context_data,
            error_message=instance.error_message,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            completed_at=instance.completed_at,
            retry_count=instance.retry_count,
        )

    def to_dict(self, saga: Saga) -> dict[str, Any]:
        """Convert domain model to dictionary for API responses."""
        return {
            "saga_id": saga.saga_id,
            "saga_name": saga.saga_name,
            "execution_id": saga.execution_id,
            "state": saga.state.value,
            "current_step": saga.current_step,
            "completed_steps": saga.completed_steps,
            "compensated_steps": saga.compensated_steps,
            "error_message": saga.error_message,
            "created_at": saga.created_at.isoformat(),
            "updated_at": saga.updated_at.isoformat(),
            "completed_at": saga.completed_at.isoformat() if saga.completed_at else None,
            "retry_count": saga.retry_count
        }


class SagaResponseMapper:
    """Maps saga domain models to Pydantic response models (API edge only)."""

    def to_response(self, saga: Saga) -> SagaStatusResponse:
        return SagaStatusResponse(
            saga_id=saga.saga_id,
            saga_name=saga.saga_name,
            execution_id=saga.execution_id,
            state=saga.state,
            current_step=saga.current_step,
            completed_steps=saga.completed_steps,
            compensated_steps=saga.compensated_steps,
            error_message=saga.error_message,
            created_at=saga.created_at.isoformat(),
            updated_at=saga.updated_at.isoformat(),
            completed_at=saga.completed_at.isoformat() if saga.completed_at else None,
            retry_count=saga.retry_count,
        )

    def list_to_responses(self, sagas: List[Saga]) -> List[SagaStatusResponse]:
        return [self.to_response(s) for s in sagas]


class SagaInstanceMapper:
    """Maps SagaInstance domain <-> Mongo documents."""

    @staticmethod
    def from_mongo(doc: dict[str, Any]) -> SagaInstance:
        
        # Robust state conversion
        raw_state = doc.get("state", SagaState.CREATED)
        try:
            state = raw_state if isinstance(raw_state, SagaState) else SagaState(str(raw_state))
        except Exception:
            state = SagaState.CREATED

        # Build kwargs conditionally
        kwargs: dict[str, Any] = {
            "saga_id": str(doc.get("saga_id")),
            "saga_name": str(doc.get("saga_name")),
            "execution_id": str(doc.get("execution_id")),
            "state": state,
            "current_step": doc.get("current_step"),
            "completed_steps": list(doc.get("completed_steps", [])),
            "compensated_steps": list(doc.get("compensated_steps", [])),
            "context_data": dict(doc.get("context_data", {})),
            "error_message": doc.get("error_message"),
            "completed_at": doc.get("completed_at"),
            "retry_count": int(doc.get("retry_count", 0)),
        }
        
        # Only add datetime fields if they exist and are valid
        if doc.get("created_at"):
            kwargs["created_at"] = doc.get("created_at")
        if doc.get("updated_at"):
            kwargs["updated_at"] = doc.get("updated_at")
        
        return SagaInstance(**kwargs)

    @staticmethod
    def to_mongo(instance: SagaInstance) -> dict[str, Any]:
        # Clean context to ensure it's serializable and skip internal keys
        clean_context: dict[str, Any] = {}
        for k, v in (instance.context_data or {}).items():
            if k.startswith("_"):
                continue
            if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                clean_context[k] = v
            else:
                try:
                    clean_context[k] = str(v)
                except Exception:
                    continue

        return {
            "saga_id": str(instance.saga_id),
            "saga_name": instance.saga_name,
            "execution_id": instance.execution_id,
            "state": instance.state.value if hasattr(instance.state, "value") else str(instance.state),
            "current_step": instance.current_step,
            "completed_steps": instance.completed_steps,
            "compensated_steps": instance.compensated_steps,
            "context_data": clean_context,
            "error_message": instance.error_message,
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
            "completed_at": instance.completed_at,
            "retry_count": instance.retry_count,
        }


class SagaEventMapper:
    """Maps saga domain objects to typed Kafka events."""

    @staticmethod
    def to_cancelled_event(
        instance: SagaInstance,
        *,
        user_id: str | None = None,
        service_name: str = "saga-orchestrator",
        service_version: str = "1.0.0",
    ) -> SagaCancelledEvent:
        cancelled_by = user_id or instance.context_data.get("user_id") or "system"
        metadata = EventMetadata(
            service_name=service_name,
            service_version=service_version,
            user_id=cancelled_by,
        )

        return SagaCancelledEvent(
            saga_id=instance.saga_id,
            saga_name=instance.saga_name,
            execution_id=instance.execution_id,
            reason=instance.error_message or "User requested cancellation",
            completed_steps=instance.completed_steps,
            compensated_steps=instance.compensated_steps,
            cancelled_at=instance.completed_at,
            cancelled_by=cancelled_by,
            metadata=metadata,
        )


class SagaFilterMapper:
    """Maps saga filters to MongoDB queries."""

    def to_mongodb_query(self, filter: SagaFilter) -> dict[str, Any]:
        """Convert filter to MongoDB query."""
        query: dict[str, Any] = {}

        if filter.state:
            query["state"] = filter.state.value

        if filter.execution_ids:
            query["execution_id"] = {"$in": filter.execution_ids}

        if filter.saga_name:
            query["saga_name"] = filter.saga_name

        if filter.error_status is not None:
            if filter.error_status:
                query["error_message"] = {"$ne": None}
            else:
                query["error_message"] = None

        if filter.created_after or filter.created_before:
            time_query: dict[str, Any] = {}
            if filter.created_after:
                time_query["$gte"] = filter.created_after
            if filter.created_before:
                time_query["$lte"] = filter.created_before
            query["created_at"] = time_query

        return query
