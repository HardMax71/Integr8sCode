import pytest
from app.core.exceptions.handlers import _map_to_status_code
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
    def test_exception_maps_to_correct_status(
        self, exception: DomainError, expected_status: int
    ) -> None:
        """Domain exception maps to correct HTTP status code."""
        assert _map_to_status_code(exception) == expected_status
