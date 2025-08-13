from typing import Any, Dict, Optional

from fastapi import HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.logging import logger
from app.db.mongodb import DatabaseManager
from app.schemas_pydantic.saga import SagaListResponse, SagaStatusResponse
from app.schemas_pydantic.user import UserResponse
from app.services.saga import SagaOrchestrator, SagaState
from app.services.saga.saga_manager import get_saga_orchestrator_manager


class SagaRepository:
    """Repository for managing saga data access"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        if db_manager.db is None:
            raise ValueError("DB is not initialized")
        self.db: AsyncIOMotorDatabase = db_manager.db
        self._orchestrator: Optional[SagaOrchestrator] = None

    async def get_orchestrator(self) -> SagaOrchestrator:
        """Get saga orchestrator instance"""
        if not self._orchestrator:
            manager = await get_saga_orchestrator_manager()
            self._orchestrator = await manager.get_orchestrator()
        return self._orchestrator

    async def get_saga_status(self, saga_id: str, current_user: UserResponse) -> SagaStatusResponse:
        """Get status of a specific saga"""
        try:
            orchestrator = await self.get_orchestrator()
            saga_instance = await orchestrator.get_saga_status(saga_id)

            if not saga_instance:
                raise HTTPException(status_code=404, detail="Saga not found")

            # Check access permissions
            execution = await self.db.executions.find_one({
                "execution_id": saga_instance.execution_id,
                "user_id": current_user.user_id
            })

            if not execution and current_user.role != "admin":
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
            state: Optional[SagaState],
            current_user: UserResponse
    ) -> SagaListResponse:
        """Get all sagas for a specific execution"""
        try:
            # Check access permissions
            execution = await self.db.executions.find_one({
                "execution_id": execution_id,
                "user_id": current_user.user_id
            })

            if not execution and current_user.role != "admin":
                raise HTTPException(status_code=404, detail="Execution not found or access denied")

            orchestrator = await self.get_orchestrator()
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
            state: Optional[SagaState],
            limit: int,
            offset: int,
            current_user: UserResponse
    ) -> SagaListResponse:
        """List sagas with filtering and pagination"""
        try:
            sagas_collection = self.db.sagas

            # Build query based on user permissions
            query: Dict[str, Any] = {}
            if current_user.role != "admin":
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


def get_saga_repository(request: Request) -> SagaRepository:
    """FastAPI dependency to get saga repository"""
    db_manager: DatabaseManager = request.app.state.db_manager
    return SagaRepository(db_manager)
