import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Dict, List, Never, Optional, Set

from fastapi import BackgroundTasks, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.logging import logger
from app.db.mongodb import DatabaseManager
from app.schemas_pydantic.projections import (
    ErrorAnalysisResponse,
    ExecutionSummaryResponse,
    LanguageUsageResponse,
    ProjectionQueryResponse,
    ProjectionStatus,
)
from app.services.event_projections import EventProjectionManager, EventProjectionService

# Python 3.12 type aliases
type ProjectionName = str
type CollectionName = str
type UserId = str
type Language = str
type Version = str
type ErrorType = str
type Month = str
type DateString = str
type FilterDict = Dict[str, Any]
type ResultDict = Dict[str, Any]
type SortDict = Dict[str, int]


# Enums
class ProjectionAction(StrEnum):
    """Valid projection management actions."""
    START = "start"
    STOP = "stop"
    REBUILD = "rebuild"


# Constants
PROJECTION_COLLECTIONS = {
    "execution_summary": "projection_execution_summary",
    "error_analysis": "projection_error_analysis",
    "language_usage": "projection_language_usage",
}

# Result messages
ACTION_RESULTS = {
    ProjectionAction.START: "started",
    ProjectionAction.STOP: "stopped",
    ProjectionAction.REBUILD: "rebuild_started",
}

# Default limits
DEFAULT_ERROR_ANALYSIS_LIMIT = 50
DEFAULT_QUERY_LIMIT = 100
MAX_SAMPLE_ERRORS = 5
TOP_ERRORS_LIMIT = 10


class ProjectionsRepository:
    """Repository for managing event projections data"""

    def __init__(self, db_manager: DatabaseManager, projection_manager: EventProjectionManager) -> None:
        self.db_manager = db_manager
        db = db_manager.db
        if db is None:
            raise RuntimeError("Database not initialized")
        self.db: AsyncIOMotorDatabase = db
        self.projection_manager = projection_manager
        self._projection_service: Optional[EventProjectionService] = None

    async def get_projection_service(self) -> EventProjectionService:
        """Get or initialize projection service"""
        if not self._projection_service:
            self._projection_service = await self.projection_manager.get_service(self.db_manager)
        return self._projection_service

    @staticmethod
    def _build_date_filter(
            start_date: Optional[DateString] = None,
            end_date: Optional[DateString] = None
    ) -> Optional[FilterDict]:
        """Build date filter for MongoDB queries."""
        if not start_date and not end_date:
            return None

        date_filter: FilterDict = {}
        if start_date:
            date_filter["$gte"] = start_date
        if end_date:
            date_filter["$lte"] = end_date
        return date_filter

    @staticmethod
    def _handle_error(error: Exception, operation: str) -> Never:
        """Handle errors consistently across all methods."""
        logger.error(f"Error {operation}: {error}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to {operation}"
        ) from error

    async def list_projections(self) -> List[ProjectionStatus]:
        """Get status of all projections"""
        try:
            projection_service = await self.get_projection_service()
            statuses = await projection_service.get_projection_status()

            result = []
            for status in statuses:
                # Ensure all required fields are present
                if 'last_processed' not in status:
                    status['last_processed'] = None
                result.append(ProjectionStatus(**status))

            return result

        except Exception as e:
            self._handle_error(e, "list projections")
            # This line is never reached due to Never return type, but mypy needs it
            raise

    async def manage_projection_action(
            self,
            action: str,
            projection_names: List[ProjectionName],
            background_tasks: Optional[BackgroundTasks] = None
    ) -> ResultDict:
        """Execute management action on projections"""
        try:
            projection_service = await self.get_projection_service()
            results: Dict[ProjectionName, str] = {}

            # Validate action
            try:
                action_enum = ProjectionAction(action)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

            for projection_name in projection_names:
                try:
                    if action_enum == ProjectionAction.START:
                        await projection_service.start_projection(projection_name)
                        results[projection_name] = ACTION_RESULTS[action_enum]

                    elif action_enum == ProjectionAction.STOP:
                        await projection_service.stop_projection(projection_name)
                        results[projection_name] = ACTION_RESULTS[action_enum]

                    elif action_enum == ProjectionAction.REBUILD:
                        if not background_tasks:
                            raise ValueError("Background tasks required for rebuild action")
                        background_tasks.add_task(
                            projection_service.rebuild_projection,
                            projection_name
                        )
                        results[projection_name] = ACTION_RESULTS[action_enum]

                except Exception as e:
                    logger.error(f"Error managing projection {projection_name}: {e}")
                    results[projection_name] = f"error: {str(e)}"

            return {
                "action": action,
                "results": results
            }

        except Exception as e:
            self._handle_error(e, "manage projections")
            raise

    async def query_projection(
            self,
            projection_name: ProjectionName,
            filters: FilterDict,
            limit: int,
            skip: int,
            sort: Optional[SortDict] = None
    ) -> ProjectionQueryResponse:
        """Query projection data"""
        try:
            projection_service = await self.get_projection_service()

            if projection_name not in projection_service.projections:
                raise HTTPException(status_code=404, detail=f"Projection {projection_name} not found")

            projection = projection_service.projections[projection_name]
            collection = self.db[projection.output_collection]

            cursor = collection.find(filters)

            if sort:
                cursor = cursor.sort(list(sort.items()))

            cursor = cursor.skip(skip).limit(limit)

            results = await cursor.to_list(None)
            total = await collection.count_documents(filters)

            # Convert to JSON-serializable format, converting ObjectId and datetime to string
            serializable_results = json.loads(json.dumps(results, default=str))

            return ProjectionQueryResponse(
                projection=projection_name,
                data=serializable_results,
                total=total,
                limit=limit,
                skip=skip
            )

        except HTTPException:
            raise
        except Exception as e:
            self._handle_error(e, "query projection")
            raise

    async def get_execution_summary(
            self,
            user_id: UserId,
            start_date: Optional[DateString] = None,
            end_date: Optional[DateString] = None
    ) -> ExecutionSummaryResponse:
        """Get execution summary for a user"""
        try:
            await self.get_projection_service()
            collection = self.db[PROJECTION_COLLECTIONS["execution_summary"]]

            query: FilterDict = {"_id.user_id": user_id}

            if date_filter := self._build_date_filter(start_date, end_date):
                query["_id.date"] = date_filter

            cursor = collection.find(query).sort("_id.date", -1)
            summaries = await cursor.to_list(None)

            # Calculate totals using aggregation
            aggregations = {
                "total_executions": lambda s: s.get("total", 0),
                "total_completed": lambda s: s.get("completed", 0),
                "total_failed": lambda s: s.get("failed", 0),
                "total_timeout": lambda s: s.get("timeout", 0),
                "total_duration": lambda s: s.get("total_duration", 0),
                "duration_count": lambda s: s.get("duration_count", 0),
            }

            totals = {key: sum(func(s) for s in summaries) for key, func in aggregations.items()}
            avg_duration = totals["total_duration"] / totals["duration_count"] if totals["duration_count"] > 0 else 0

            languages: Set[Language] = set()
            for s in summaries:
                if langs := s.get("languages"):
                    languages.update(langs)

            return ExecutionSummaryResponse(
                user_id=user_id,
                period={
                    "start": start_date or (summaries[-1]["_id"]["date"] if summaries else None),
                    "end": end_date or (summaries[0]["_id"]["date"] if summaries else None)
                },
                totals={
                    "executions": totals["total_executions"],
                    "completed": totals["total_completed"],
                    "failed": totals["total_failed"],
                    "timeout": totals["total_timeout"],
                    "success_rate": (totals["total_completed"] / totals["total_executions"] * 100)
                    if totals["total_executions"] > 0 else 0
                },
                performance={
                    "avg_duration_seconds": round(avg_duration, 2),
                    "languages_used": sorted(list(languages))
                },
                daily_summaries=summaries
            )

        except Exception as e:
            self._handle_error(e, "get execution summary")
            raise

    async def get_error_analysis(
            self,
            language: Optional[Language] = None,
            start_date: Optional[DateString] = None,
            end_date: Optional[DateString] = None,
            limit: int = DEFAULT_ERROR_ANALYSIS_LIMIT
    ) -> ErrorAnalysisResponse:
        """Get error analysis data"""
        try:
            await self.get_projection_service()
            collection = self.db[PROJECTION_COLLECTIONS["error_analysis"]]

            query: FilterDict = {}

            if language:
                query["_id.language"] = language

            if date_filter := self._build_date_filter(start_date, end_date):
                query["_id.date"] = date_filter

            cursor = collection.find(query).sort("count", -1).limit(limit)
            errors = await cursor.to_list(None)

            # Aggregate error summary
            error_summary: Dict[ErrorType, Dict[str, Any]] = {}
            for error in errors:
                error_type: ErrorType = error["_id"]["error_type"]
                if error_type not in error_summary:
                    error_summary[error_type] = {
                        "total_occurrences": 0,
                        "languages": set(),
                        "sample_errors": []
                    }

                error_summary[error_type]["total_occurrences"] += error.get("count", 0)
                error_summary[error_type]["languages"].add(error["_id"]["language"])

                if samples := error.get("sample_errors"):
                    error_summary[error_type]["sample_errors"].extend(samples[:2])

            # Format the summary
            for error_type in error_summary:
                error_summary[error_type]["languages"] = sorted(
                    list(error_summary[error_type]["languages"])
                )
                error_summary[error_type]["sample_errors"] = (
                    error_summary[error_type]["sample_errors"][:MAX_SAMPLE_ERRORS]
                )

            return ErrorAnalysisResponse(
                period={
                    "start": start_date,
                    "end": end_date
                },
                filter={
                    "language": language
                },
                error_types=error_summary,
                top_errors=errors[:TOP_ERRORS_LIMIT]
            )

        except Exception as e:
            self._handle_error(e, "get error analysis")
            raise

    async def get_language_usage(self, month: Optional[Month] = None) -> LanguageUsageResponse:
        """Get language usage statistics"""
        try:
            await self.get_projection_service()
            collection = self.db[PROJECTION_COLLECTIONS["language_usage"]]

            query: FilterDict = {}
            if month:
                query["_id.month"] = month

            cursor = collection.find(query).sort("usage_count", -1)
            usage_data = await cursor.to_list(None)

            # Aggregate language data
            language_summary: Dict[Language, Dict[str, Any]] = {}
            for item in usage_data:
                lang: Language = item["_id"]["language"]
                version: Version = item["_id"]["version"]

                if lang not in language_summary:
                    language_summary[lang] = {
                        "total_usage": 0,
                        "versions": {},
                        "unique_users": set(),
                        "last_used": None
                    }

                language_summary[lang]["total_usage"] += item.get("usage_count", 0)
                language_summary[lang]["versions"][version] = item.get("usage_count", 0)

                if users := item.get("users"):
                    language_summary[lang]["unique_users"].update(users)

                last_used: Optional[datetime] = item.get("last_used")
                if last_used and (
                        not language_summary[lang]["last_used"] or
                        last_used > language_summary[lang]["last_used"]
                ):
                    language_summary[lang]["last_used"] = last_used

            # Format the summary
            formatted_summary: Dict[Language, Dict[str, Any]] = {}
            for lang, data in language_summary.items():
                formatted_summary[lang] = {
                    "total_usage": data["total_usage"],
                    "versions": data["versions"],
                    "unique_users": len(data["unique_users"]),
                    "last_used": data["last_used"].isoformat() if data["last_used"] else None
                }

            sorted_languages = sorted(
                formatted_summary.items(),
                key=lambda x: x[1]["total_usage"],
                reverse=True
            )

            return LanguageUsageResponse(
                month=month,
                languages=dict(sorted_languages),
                total_languages=len(sorted_languages)
            )

        except Exception as e:
            self._handle_error(e, "get language usage")
            raise


def get_projections_repository(request: Request) -> ProjectionsRepository:
    """FastAPI dependency to get projections repository"""
    db_manager: DatabaseManager = request.app.state.db_manager
    projection_manager: EventProjectionManager = request.app.state.projection_manager
    return ProjectionsRepository(db_manager, projection_manager)
