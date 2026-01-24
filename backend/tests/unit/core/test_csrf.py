import pytest
from app.core.security import SecurityService
from app.domain.user.exceptions import CSRFValidationError
from app.settings import Settings
from starlette.requests import Request


def make_request(
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> Request:
    """Create a mock Starlette Request for testing."""
    headers = headers or {}
    if cookies:
        cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers = {**headers, "cookie": cookie_header}
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    return Request(scope)


class TestCSRFTokenGeneration:
    """Tests for CSRF token generation."""

    def test_generates_token_with_sufficient_entropy(
        self, test_settings: Settings
    ) -> None:
        """CSRF token is generated with sufficient entropy."""
        security = SecurityService(test_settings)

        token = security.generate_csrf_token()

        assert isinstance(token, str)
        # token_urlsafe(32) produces ~43 characters
        assert len(token) >= 40

    def test_generates_unique_tokens(self, test_settings: Settings) -> None:
        """Each CSRF token is unique."""
        security = SecurityService(test_settings)

        tokens = {security.generate_csrf_token() for _ in range(100)}

        # All 100 tokens should be unique
        assert len(tokens) == 100


class TestCSRFTokenValidation:
    """Tests for CSRF token validation."""

    def test_validates_matching_tokens(self, test_settings: Settings) -> None:
        """Matching CSRF tokens pass validation."""
        security = SecurityService(test_settings)
        token = security.generate_csrf_token()

        result = security.validate_csrf_token(token, token)

        assert result is True

    def test_rejects_mismatched_tokens(self, test_settings: Settings) -> None:
        """Mismatched CSRF tokens fail validation."""
        security = SecurityService(test_settings)

        token1 = security.generate_csrf_token()
        token2 = security.generate_csrf_token()

        result = security.validate_csrf_token(token1, token2)

        assert result is False

    @pytest.mark.parametrize(
        ("header_token", "cookie_token"),
        [
            ("", "valid_token"),
            ("valid_token", ""),
            ("", ""),
        ],
        ids=["empty_header", "empty_cookie", "both_empty"],
    )
    def test_rejects_empty_tokens(
        self, test_settings: Settings, header_token: str, cookie_token: str
    ) -> None:
        """Empty CSRF tokens fail validation."""
        security = SecurityService(test_settings)

        result = security.validate_csrf_token(header_token, cookie_token)

        assert result is False


class TestCSRFExemptPaths:
    """Tests for CSRF exempt path configuration."""

    def test_exempt_paths_includes_auth_endpoints(
        self, test_settings: Settings
    ) -> None:
        """CSRF exempt paths include auth endpoints."""
        security = SecurityService(test_settings)

        assert "/api/v1/auth/login" in security.CSRF_EXEMPT_PATHS
        assert "/api/v1/auth/register" in security.CSRF_EXEMPT_PATHS
        assert "/api/v1/auth/logout" in security.CSRF_EXEMPT_PATHS

    def test_exempt_paths_is_frozenset(self, test_settings: Settings) -> None:
        """CSRF exempt paths is a frozenset (immutable)."""
        security = SecurityService(test_settings)

        assert isinstance(security.CSRF_EXEMPT_PATHS, frozenset)


class TestCSRFRequestValidation:
    """Tests for CSRF validation from HTTP requests."""

    def test_skips_get_requests(self, test_settings: Settings) -> None:
        """GET requests skip CSRF validation."""
        security = SecurityService(test_settings)
        req = make_request("GET", "/api/v1/anything")

        assert security.validate_csrf_from_request(req) == "skip"

    def test_missing_header_raises_when_authenticated(
        self, test_settings: Settings
    ) -> None:
        """Missing CSRF header raises error for authenticated POST."""
        security = SecurityService(test_settings)
        req = make_request(
            "POST",
            "/api/v1/items",
            cookies={"access_token": "tok", "csrf_token": "abc"},
        )

        with pytest.raises(CSRFValidationError):
            security.validate_csrf_from_request(req)

    def test_valid_tokens_pass(self, test_settings: Settings) -> None:
        """Valid matching CSRF tokens pass validation."""
        security = SecurityService(test_settings)
        token = security.generate_csrf_token()
        req = make_request(
            "POST",
            "/api/v1/items",
            headers={"X-CSRF-Token": token},
            cookies={"access_token": "tok", "csrf_token": token},
        )

        assert security.validate_csrf_from_request(req) == token
