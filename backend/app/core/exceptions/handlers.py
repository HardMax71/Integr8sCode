from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.domain.exceptions import (
    AccountLockedError,
    ConflictError,
    DomainError,
    ForbiddenError,
    InfrastructureError,
    InvalidStateError,
    NotFoundError,
    ThrottledError,
    UnauthorizedError,
    ValidationError,
)
from app.schemas_pydantic.common import ErrorResponse


# --8<-- [start:configure_exception_handlers]
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    status = _map_to_status_code(exc)
    return JSONResponse(ErrorResponse(status=status, detail=exc.message).model_dump(), status_code=status)


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        ErrorResponse(status=exc.status_code, detail=exc.detail).model_dump(),
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    detail = "; ".join(f"{error['loc'][-1]}: {error['msg']}" for error in exc.errors())
    return JSONResponse(ErrorResponse(status=422, detail=detail).model_dump(), status_code=422)


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(ErrorResponse(status=500, detail="Internal server error").model_dump(), status_code=500)


def configure_exception_handlers(app: FastAPI) -> None:
    app.exception_handler(DomainError)(domain_error_handler)
    app.exception_handler(HTTPException)(http_error_handler)
    app.exception_handler(RequestValidationError)(validation_error_handler)
    # Starlette's outermost middleware sends this, then re-raises so the server still logs the traceback
    app.exception_handler(Exception)(unexpected_error_handler)


def _map_to_status_code(exc: DomainError) -> int:
    if isinstance(exc, NotFoundError):
        return 404
    if isinstance(exc, ValidationError):
        return 422
    if isinstance(exc, ThrottledError):
        return 429
    if isinstance(exc, ConflictError):
        return 409
    if isinstance(exc, UnauthorizedError):
        return 401
    if isinstance(exc, ForbiddenError):
        return 403
    if isinstance(exc, InvalidStateError):
        return 400
    if isinstance(exc, AccountLockedError):
        return 423
    if isinstance(exc, InfrastructureError):
        return 500
    return 500


# --8<-- [end:configure_exception_handlers]
