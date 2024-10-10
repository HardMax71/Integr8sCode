from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

class IntegrationException(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail

def configure_exception_handlers(app: FastAPI):
    @app.exception_handler(IntegrationException)
    async def integration_exception_handler(request: Request, exc: IntegrationException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )