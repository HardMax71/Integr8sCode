import httpx2
import pytest
from fastapi import FastAPI, HTTPException

from app.core.exceptions.handlers import _map_to_status_code, configure_exception_handlers
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


class TestExceptionMapping:
    """Tests for domain exception to HTTP status code mapping."""

    @pytest.mark.parametrize(
        ("exception", "expected_status"),
        [
            (NotFoundError(entity="User", identifier="123"), 404),
            (ValidationError(message="Invalid input"), 422),
            (ThrottledError(message="Rate limit exceeded"), 429),
            (ConflictError(message="Resource already exists"), 409),
            (UnauthorizedError(message="Invalid credentials"), 401),
            (ForbiddenError(message="Access denied"), 403),
            (InvalidStateError(message="Invalid state transition"), 400),
            (InfrastructureError(message="Database connection failed"), 500),
            (DomainError(message="Unknown error"), 500),
        ],
        ids=[
            "not_found_404",
            "validation_422",
            "throttled_429",
            "conflict_409",
            "unauthorized_401",
            "forbidden_403",
            "invalid_state_400",
            "infrastructure_500",
            "generic_domain_500",
        ],
    )
    def test_exception_maps_to_correct_status(self, exception: DomainError, expected_status: int) -> None:
        """Domain exception maps to correct HTTP status code."""
        assert _map_to_status_code(exception) == expected_status


def _app() -> FastAPI:
    app = FastAPI()
    configure_exception_handlers(app)

    @app.get("/domain")
    async def domain() -> None:
        raise NotFoundError("Saga", "s-1")

    @app.get("/http")
    async def http() -> None:
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/validated")
    async def validated(limit: int) -> int:
        return limit

    @app.get("/crash")
    async def crash() -> None:
        raise RuntimeError("boom")

    return app


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/domain", {"status": 404, "detail": "Saga 's-1' not found"}),
        ("/http", {"status": 401, "detail": "Not authenticated"}),
        (
            "/validated?limit=x",
            {"status": 422, "detail": "limit: Input should be a valid integer, unable to parse string as an integer"},
        ),
        ("/missing", {"status": 404, "detail": "Not Found"}),
        ("/crash", {"status": 500, "detail": "Internal server error"}),
    ],
)
async def test_every_error_has_the_same_body(path: str, body: dict[str, object]) -> None:
    transport = httpx2.ASGITransport(app=_app(), raise_app_exceptions=False)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(path)
    assert (response.status_code, response.json()) == (body["status"], body)


async def test_http_error_keeps_its_headers() -> None:
    transport = httpx2.ASGITransport(app=_app())
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/http")
    assert response.headers["WWW-Authenticate"] == "Bearer"
