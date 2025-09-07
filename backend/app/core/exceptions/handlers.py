from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions.base import AuthenticationError, IntegrationException, ServiceError
from app.domain.saga.exceptions import (
    SagaAccessDeniedError,
    SagaInvalidStateError,
    SagaNotFoundError,
)


def configure_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(IntegrationException)
    async def integration_exception_handler(
            request: Request, exc: IntegrationException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(AuthenticationError)
    async def authentication_error_handler(
            request: Request, exc: AuthenticationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": exc.detail},
        )

    @app.exception_handler(ServiceError)
    async def service_error_handler(
            request: Request, exc: ServiceError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
        )

    @app.exception_handler(SagaNotFoundError)
    async def saga_not_found_handler(
            request: Request, exc: SagaNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Saga not found"})

    @app.exception_handler(SagaAccessDeniedError)
    async def saga_access_denied_handler(
            request: Request, exc: SagaAccessDeniedError
    ) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": "Access denied"})

    @app.exception_handler(SagaInvalidStateError)
    async def saga_invalid_state_handler(
            request: Request, exc: SagaInvalidStateError
    ) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
