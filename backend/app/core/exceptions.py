from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class IntegrationException(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


class AuthenticationError(Exception):
    """Exception raised for authentication errors"""
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class ServiceError(Exception):
    """Exception raised for service-related errors"""
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


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
