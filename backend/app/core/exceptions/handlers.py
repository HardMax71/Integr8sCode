from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.exceptions import (
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


# --8<-- [start:configure_exception_handlers]
def configure_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        status_code = _map_to_status_code(exc)
        return JSONResponse(
            status_code=status_code,
            content={"detail": exc.message, "type": type(exc).__name__},
        )


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
    if isinstance(exc, InfrastructureError):
        return 500
    return 500
# --8<-- [end:configure_exception_handlers]
