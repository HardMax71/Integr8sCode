from fastapi import APIRouter, Depends, HTTPException, Request
from app.core.exceptions import IntegrationException
from app.core.security import security_service
from app.models.user import UserInDB
from app.schemas.execution import ExecutionRequest, ExecutionResponse, ExecutionResult, K8SResourceLimits
from app.services.execution_service import ExecutionService, get_execution_service
from slowapi import Limiter
from slowapi.util import get_remote_address

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/execute", response_model=ExecutionResponse)
@limiter.limit("20/minute")
async def create_execution(
        request: Request,
        execution: ExecutionRequest,
        current_user: UserInDB = Depends(security_service.get_current_user),
        execution_service: ExecutionService = Depends(get_execution_service)
):
    try:
        result = await execution_service.execute_script(execution.script)
        return ExecutionResponse(execution_id=result.id, status=result.status)
    except IntegrationException as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error during execution: {str(e)}")


@router.get("/result/{execution_id}", response_model=ExecutionResult)
@limiter.limit("20/minute")
async def get_result(
        request: Request,
        execution_id: str,
        current_user: UserInDB = Depends(security_service.get_current_user),
        execution_service: ExecutionService = Depends(get_execution_service)
):
    result = await execution_service.get_execution_result(execution_id)
    if not result:
        raise HTTPException(status_code=404, detail="Execution not found")
    return ExecutionResult(
        execution_id=result.id,
        status=result.status,
        output=result.output,
        errors=result.errors
    )


@router.get("/k8s-limits", response_model=K8SResourceLimits)
async def get_k8s_resource_limits(
        current_user: UserInDB = Depends(security_service.get_current_user),
        execution_service: ExecutionService = Depends(get_execution_service)
):
    try:
        limits = await execution_service.get_k8s_resource_limits()
        return K8SResourceLimits(**limits)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")
