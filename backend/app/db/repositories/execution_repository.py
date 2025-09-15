from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.logging import logger
from app.domain.enums.execution import ExecutionStatus
from app.domain.events.event_models import CollectionNames
from app.domain.execution import DomainExecution, ExecutionResultDomain, ResourceUsageDomain


class ExecutionRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection: AsyncIOMotorCollection = self.db.get_collection(CollectionNames.EXECUTIONS)
        self.results_collection: AsyncIOMotorCollection = self.db.get_collection(CollectionNames.EXECUTION_RESULTS)

    async def create_execution(self, execution: DomainExecution) -> DomainExecution:
        execution_dict = {
            "execution_id": execution.execution_id,
            "script": execution.script,
            "status": execution.status,
            "stdout": execution.stdout,
            "stderr": execution.stderr,
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

    async def get_execution(self, execution_id: str) -> DomainExecution | None:
        logger.info(f"Searching for execution {execution_id} in MongoDB")
        document = await self.collection.find_one({"execution_id": execution_id})
        if not document:
            logger.warning(f"Execution {execution_id} not found in MongoDB")
            return None

        logger.info(f"Found execution {execution_id} in MongoDB")

        result_doc = await self.results_collection.find_one({"execution_id": execution_id})
        if result_doc:
            document["stdout"] = result_doc.get("stdout")
            document["stderr"] = result_doc.get("stderr")
            document["exit_code"] = result_doc.get("exit_code")
            document["resource_usage"] = result_doc.get("resource_usage")
            document["error_type"] = result_doc.get("error_type")
            if result_doc.get("status"):
                document["status"] = result_doc.get("status")

        sv = document.get("status")
        return DomainExecution(
            execution_id=document.get("execution_id"),
            script=document.get("script", ""),
            status=ExecutionStatus(str(sv)),
            stdout=document.get("stdout"),
            stderr=document.get("stderr"),
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

    async def update_execution(self, execution_id: str, update_data: dict) -> bool:
        update_data.setdefault("updated_at", datetime.now(timezone.utc))
        update_payload = {"$set": update_data}

        result = await self.collection.update_one(
            {"execution_id": execution_id}, update_payload
        )
        return result.matched_count > 0

    async def write_terminal_result(self, exec_result: ExecutionResultDomain) -> bool:
        base = await self.collection.find_one({"execution_id": exec_result.execution_id}, {"user_id": 1}) or {}
        user_id = base.get("user_id")

        doc = {
            "_id": exec_result.execution_id,
            "execution_id": exec_result.execution_id,
            "status": exec_result.status.value,
            "exit_code": exec_result.exit_code,
            "stdout": exec_result.stdout,
            "stderr": exec_result.stderr,
            "resource_usage": exec_result.resource_usage.to_dict(),
            "created_at": exec_result.created_at,
            "metadata": exec_result.metadata,
        }
        if exec_result.error_type is not None:
            doc["error_type"] = exec_result.error_type
        if user_id is not None:
            doc["user_id"] = user_id

        await self.results_collection.replace_one({"_id": exec_result.execution_id}, doc, upsert=True)

        update_data = {
            "status": exec_result.status.value,
            "updated_at": datetime.now(timezone.utc),
            "stdout": exec_result.stdout,
            "stderr": exec_result.stderr,
            "exit_code": exec_result.exit_code,
            "resource_usage": exec_result.resource_usage.to_dict(),
        }
        if exec_result.error_type is not None:
            update_data["error_type"] = exec_result.error_type

        res = await self.collection.update_one({"execution_id": exec_result.execution_id}, {"$set": update_data})
        if res.matched_count == 0:
            logger.warning(f"No execution found to patch for {exec_result.execution_id} after result upsert")
        return True

    async def get_executions(
            self,
            query: dict,
            limit: int = 50,
            skip: int = 0,
            sort: list | None = None
    ) -> list[DomainExecution]:
        cursor = self.collection.find(query)
        if sort:
            cursor = cursor.sort(sort)
        cursor = cursor.skip(skip).limit(limit)

        executions: list[DomainExecution] = []
        async for doc in cursor:
            sv = doc.get("status")
            executions.append(
                DomainExecution(
                    execution_id=doc.get("execution_id"),
                    script=doc.get("script", ""),
                    status=ExecutionStatus(str(sv)),
                    stdout=doc.get("stdout"),
                    stderr=doc.get("stderr"),
                    lang=doc.get("lang", "python"),
                    lang_version=doc.get("lang_version", "3.11"),
                    created_at=doc.get("created_at", datetime.now(timezone.utc)),
                    updated_at=doc.get("updated_at", datetime.now(timezone.utc)),
                    resource_usage=(
                        ResourceUsageDomain.from_dict(doc.get("resource_usage"))
                        if doc.get("resource_usage") is not None
                        else None
                    ),
                    user_id=doc.get("user_id"),
                    exit_code=doc.get("exit_code"),
                    error_type=doc.get("error_type"),
                )
            )

        return executions

    async def count_executions(self, query: dict) -> int:
        return await self.collection.count_documents(query)

    async def delete_execution(self, execution_id: str) -> bool:
        result = await self.collection.delete_one({"execution_id": execution_id})
        return result.deleted_count > 0
