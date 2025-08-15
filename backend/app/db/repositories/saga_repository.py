from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.logging import logger
from app.schemas_pydantic.saga import SagaListResponse, SagaStatusResponse
from app.schemas_pydantic.user import UserResponse, UserRole
from app.services.saga import SagaOrchestrator, SagaState

# Removed saga manager import - will use dependency injection


class SagaRepository:
    """Repository for managing saga data access"""

    def __init__(self, database: AsyncIOMotorDatabase):
        self.db: AsyncIOMotorDatabase = database

    async def get_saga_status(self,
                              saga_id: str,
                              current_user: UserResponse,
                              orchestrator: SagaOrchestrator) -> SagaStatusResponse:
        """Get status of a specific saga"""
        try:
            saga_instance = await orchestrator.get_saga_status(saga_id)

            if not saga_instance:
                raise HTTPException(status_code=404, detail="Saga not found")

            # Check access permissions
            execution = await self.db.executions.find_one({
                "execution_id": saga_instance.execution_id,
                "user_id": current_user.user_id
            })

            if not execution and current_user.role != UserRole.ADMIN:
                raise HTTPException(status_code=404, detail="Saga not found or access denied")

            return SagaStatusResponse(
                saga_id=saga_instance.saga_id,
                saga_name=saga_instance.saga_name,
                execution_id=saga_instance.execution_id,
                state=saga_instance.state,
                current_step=saga_instance.current_step,
                completed_steps=saga_instance.completed_steps,
                compensated_steps=saga_instance.compensated_steps,
                error_message=saga_instance.error_message,
                created_at=saga_instance.created_at.isoformat(),
                updated_at=saga_instance.updated_at.isoformat(),
                completed_at=saga_instance.completed_at.isoformat() if saga_instance.completed_at else None,
                retry_count=saga_instance.retry_count,
            )
        except Exception as e:
            logger.error(f"Error getting saga status: {e}")
            raise HTTPException(status_code=500, detail="Internal server error") from e

    async def get_execution_sagas(
            self,
            execution_id: str,
            state: SagaState | None,
            current_user: UserResponse,
            orchestrator: SagaOrchestrator
    ) -> SagaListResponse:
        """Get all sagas for a specific execution"""
        try:
            # Check access permissions
            execution = await self.db.executions.find_one({
                "execution_id": execution_id,
                "user_id": current_user.user_id
            })

            if not execution and current_user.role != UserRole.ADMIN:
                raise HTTPException(status_code=404, detail="Execution not found or access denied")

            saga_instances = await orchestrator.get_execution_sagas(execution_id)

            # Filter by state if provided
            if state:
                saga_instances = [s for s in saga_instances if s.state == state]

            sagas = [
                SagaStatusResponse(
                    saga_id=instance.saga_id,
                    saga_name=instance.saga_name,
                    execution_id=instance.execution_id,
                    state=instance.state,
                    current_step=instance.current_step,
                    completed_steps=instance.completed_steps,
                    compensated_steps=instance.compensated_steps,
                    error_message=instance.error_message,
                    created_at=instance.created_at.isoformat(),
                    updated_at=instance.updated_at.isoformat(),
                    completed_at=instance.completed_at.isoformat() if instance.completed_at else None,
                    retry_count=instance.retry_count,
                )
                for instance in saga_instances
            ]

            return SagaListResponse(
                sagas=sagas,
                total=len(sagas),
            )
        except Exception as e:
            logger.error(f"Error getting execution sagas: {e}")
            raise HTTPException(status_code=500, detail="Internal server error") from e

    async def list_sagas(
            self,
            state: SagaState | None,
            limit: int,
            offset: int,
            current_user: UserResponse
    ) -> SagaListResponse:
        """List sagas with filtering and pagination"""
        try:
            sagas_collection = self.db.sagas

            # Build query based on user permissions
            query: dict[str, object] = {}
            if current_user.role != UserRole.ADMIN:
                # Get user's executions
                user_executions = await self.db.executions.distinct(
                    "_id",
                    {"user_id": current_user.user_id}
                )
                query["execution_id"] = {"$in": [str(exec_id) for exec_id in user_executions]}

            if state:
                query["state"] = state.value

            # Get total count
            total = await sagas_collection.count_documents(query)

            # Get saga documents with pagination
            saga_docs = await sagas_collection.find(query).skip(offset).limit(limit).to_list(length=limit)

            # Convert to response format
            sagas = [
                SagaStatusResponse(
                    saga_id=str(doc["saga_id"]),
                    saga_name=doc["saga_name"],
                    execution_id=str(doc["execution_id"]),
                    state=SagaState(doc["state"]),
                    current_step=doc.get("current_step"),
                    completed_steps=doc.get("completed_steps", []),
                    compensated_steps=doc.get("compensated_steps", []),
                    error_message=doc.get("error_message"),
                    created_at=doc["created_at"].isoformat(),
                    updated_at=doc["updated_at"].isoformat(),
                    completed_at=doc["completed_at"].isoformat() if doc.get("completed_at") else None,
                    retry_count=doc.get("retry_count", 0),
                )
                for doc in saga_docs
            ]

            return SagaListResponse(
                sagas=sagas,
                total=total,
            )

        except Exception as e:
            logger.error(f"Error listing sagas: {e}")
            raise HTTPException(status_code=500, detail="Internal server error") from e
