from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends

from app.api.dependencies import require_admin
from app.core.service_dependencies import ProjectionRepositoryDep
from app.schemas_pydantic.projections import (
    ErrorAnalysisResponse,
    ExecutionSummaryResponse,
    LanguageUsageResponse,
    ProjectionActionRequest,
    ProjectionQueryRequest,
    ProjectionQueryResponse,
    ProjectionStatus,
)
from app.schemas_pydantic.user import UserResponse

router = APIRouter(prefix="/projections", tags=["projections"])


@router.get("/", response_model=list[ProjectionStatus])
async def list_projections(
        repository: ProjectionRepositoryDep,
        current_user: UserResponse = Depends(require_admin)
) -> list[ProjectionStatus]:
    """List all projections and their status"""
    return await repository.list_projections()


@router.post("/actions")
async def manage_projections(
        request: ProjectionActionRequest,
        background_tasks: BackgroundTasks,
        repository: ProjectionRepositoryDep,
        current_user: UserResponse = Depends(require_admin)
) -> dict[str, Any]:
    """Manage projection actions (start, stop, rebuild)"""
    return await repository.manage_projection_action(
        action=request.action,
        projection_names=request.projection_names,
        background_tasks=background_tasks
    )


@router.post("/query", response_model=ProjectionQueryResponse)
async def query_projection(
        request: ProjectionQueryRequest,
        repository: ProjectionRepositoryDep,
        current_user: UserResponse = Depends(require_admin)
) -> ProjectionQueryResponse:
    """Query projection data"""
    return await repository.query_projection(
        projection_name=request.projection_name,
        filters=request.filters or {},
        limit=request.limit,
        skip=request.skip,
        sort=request.sort
    )


@router.get("/execution-summary/{user_id}", response_model=ExecutionSummaryResponse)
async def get_execution_summary(
        user_id: str,
        repository: ProjectionRepositoryDep,
        start_date: str | None = None,
        end_date: str | None = None,
        current_user: UserResponse = Depends(require_admin)
) -> ExecutionSummaryResponse:
    """Get execution summary for a user"""
    return await repository.get_execution_summary(
        user_id=user_id,
        start_date=start_date,
        end_date=end_date
    )


@router.get("/error-analysis", response_model=ErrorAnalysisResponse)
async def get_error_analysis(
        repository: ProjectionRepositoryDep,
        language: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 50,
        current_user: UserResponse = Depends(require_admin)
) -> ErrorAnalysisResponse:
    """Get error analysis from projections"""
    return await repository.get_error_analysis(
        language=language,
        start_date=start_date,
        end_date=end_date,
        limit=limit
    )


@router.get("/language-usage", response_model=LanguageUsageResponse)
async def get_language_usage(
        repository: ProjectionRepositoryDep,
        month: str | None = None,
        current_user: UserResponse = Depends(require_admin)
) -> LanguageUsageResponse:
    """Get language usage statistics"""
    return await repository.get_language_usage(month=month)
