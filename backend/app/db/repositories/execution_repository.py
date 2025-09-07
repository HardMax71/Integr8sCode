from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.logging import logger
from app.domain.execution.models import DomainExecution, ExecutionResultDomain, ResourceUsageDomain


class ExecutionRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection: AsyncIOMotorCollection = self.db.get_collection("executions")
        self.results_collection: AsyncIOMotorCollection = self.db.get_collection("execution_results")

    async def create_execution(self, execution: DomainExecution) -> DomainExecution:
        try:
            execution_dict = {
                "execution_id": execution.execution_id,
                "script": execution.script,
                "status": execution.status,
                "output": execution.output,
                "errors": execution.errors,
                "lang": execution.lang,
                "lang_version": execution.lang_version,
                "created_at": execution.created_at,
                "updated_at": execution.updated_at,
                "resource_usage": execution.resource_usage.to_dict() if execution.resource_usage else None,
                "user_id": execution.user_id,
                "exit_code": execution.exit_code,
                "error_type": execution.error_type,
            }
            logger.info(f"Inserting execution {execution.execution_id} into MongoDB")
            result = await self.collection.insert_one(execution_dict)
            logger.info(f"Inserted execution {execution.execution_id} with _id: {result.inserted_id}")
            return execution
        except Exception as e:
            logger.error(f"Database error creating execution {execution.execution_id}: {type(e).__name__}",
                         exc_info=True)
            raise

    async def get_execution(self, execution_id: str) -> DomainExecution | None:
        try:
            logger.info(f"Searching for execution {execution_id} in MongoDB")
            document = await self.collection.find_one({"execution_id": execution_id})
            if document:
                logger.info(f"Found execution {execution_id} in MongoDB")
                from app.domain.enums.execution import ExecutionStatus
                sv = document.get("status")
                try:
                    st = sv if isinstance(sv, ExecutionStatus) else ExecutionStatus(str(sv))
                except Exception:
                    st = ExecutionStatus.QUEUED
                return DomainExecution(
                    execution_id=document.get("execution_id"),
                    script=document.get("script", ""),
                    status=st,
                    output=document.get("output"),
                    errors=document.get("errors"),
                    lang=document.get("lang", "python"),
                    lang_version=document.get("lang_version", "3.11"),
                    created_at=document.get("created_at", datetime.now(timezone.utc)),
                    updated_at=document.get("updated_at", datetime.now(timezone.utc)),
                    resource_usage=(
                        ResourceUsageDomain.from_dict(document.get("resource_usage"))
                        if document.get("resource_usage") is not None
                        else None
                    ),
                    user_id=document.get("user_id"),
                    exit_code=document.get("exit_code"),
                    error_type=document.get("error_type"),
                )
            else:
                logger.warning(f"Execution {execution_id} not found in MongoDB")
            return None
        except Exception as e:
            logger.error(f"Database error fetching execution {execution_id}: {type(e).__name__}", exc_info=True)
            return None

    async def update_execution(self, execution_id: str, update_data: dict) -> bool:
        try:
            update_data.setdefault("updated_at", datetime.now(timezone.utc))
            update_payload = {"$set": update_data}

            result = await self.collection.update_one(
                {"execution_id": execution_id}, update_payload
            )
            return result.matched_count > 0
        except Exception as e:
            logger.error(f"Database error updating execution {execution_id}: {type(e).__name__}", exc_info=True)
            return False

    async def get_executions(
            self,
            query: dict,
            limit: int = 50,
            skip: int = 0,
            sort: list | None = None
    ) -> list[DomainExecution]:
        try:
            cursor = self.collection.find(query)
            if sort:
                cursor = cursor.sort(sort)
            cursor = cursor.skip(skip).limit(limit)

            executions: list[DomainExecution] = []
            async for doc in cursor:
                from app.domain.enums.execution import ExecutionStatus
                sv = doc.get("status")
                try:
                    st = sv if isinstance(sv, ExecutionStatus) else ExecutionStatus(str(sv))
                except Exception:
                    st = ExecutionStatus.QUEUED
                executions.append(
                    DomainExecution(
                        execution_id=doc.get("execution_id"),
                        script=doc.get("script", ""),
                        status=st,
                        output=doc.get("output"),
                        errors=doc.get("errors"),
                        lang=doc.get("lang", "python"),
                        lang_version=doc.get("lang_version", "3.11"),
                        created_at=doc.get("created_at", datetime.now(timezone.utc)),
                        updated_at=doc.get("updated_at", datetime.now(timezone.utc)),
                        resource_usage=ResourceUsageDomain.from_dict(doc.get("resource_usage")),
                        user_id=doc.get("user_id"),
                        exit_code=doc.get("exit_code"),
                        error_type=doc.get("error_type"),
                    )
                )

            return executions
        except Exception as e:
            logger.error(f"Database error fetching executions: {type(e).__name__}", exc_info=True)
            return []

    async def count_executions(self, query: dict) -> int:
        try:
            return await self.collection.count_documents(query)
        except Exception as e:
            logger.error(f"Database error counting executions: {type(e).__name__}", exc_info=True)
            return 0

    async def delete_execution(self, execution_id: str) -> bool:
        try:
            result = await self.collection.delete_one({"execution_id": execution_id})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Database error deleting execution {execution_id}: {type(e).__name__}", exc_info=True)
            return False

    async def upsert_result(self, result: ExecutionResultDomain) -> bool:
        """Create or update an execution result record.

        Stored in the dedicated 'execution_results' collection.
        """
        try:
            doc = {
                "_id": result.execution_id,
                "execution_id": result.execution_id,
                "status": result.status.value,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "resource_usage": result.resource_usage.to_dict(),
                "created_at": result.created_at,
                "metadata": result.metadata,
            }
            if result.error_type is not None:
                doc["error_type"] = result.error_type

            await self.results_collection.replace_one({"_id": result.execution_id}, doc, upsert=True)
            return True
        except Exception as e:
            logger.error(f"Database error upserting result {result.execution_id}: {type(e).__name__}", exc_info=True)
            return False
