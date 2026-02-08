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

    def test_generates_signed_token_format(self, test_settings: Settings) -> None:
        """CSRF token has nonce.signature format."""
        security = SecurityService(test_settings)

        token = security.generate_csrf_token("session-abc")

        parts = token.split(".", 1)
        assert len(parts) == 2
        nonce, signature = parts
        assert len(nonce) > 0
        assert len(signature) == 64  # sha256 hexdigest

    def test_generates_unique_tokens(self, test_settings: Settings) -> None:
        """Each CSRF token is unique (different nonce each time)."""
        security = SecurityService(test_settings)

        tokens = {security.generate_csrf_token("same-session") for _ in range(100)}

        assert len(tokens) == 100

    def test_different_sessions_produce_different_tokens(self, test_settings: Settings) -> None:
        """Tokens for different sessions differ even with same nonce derivation."""
        security = SecurityService(test_settings)

        token_a = security.generate_csrf_token("session-a")
        token_b = security.generate_csrf_token("session-b")

        assert token_a != token_b


class TestCSRFTokenValidation:
    """Tests for CSRF token validation (double-submit check)."""

    def test_validates_matching_tokens(self, test_settings: Settings) -> None:
        """Matching CSRF tokens pass validation."""
        security = SecurityService(test_settings)
        token = security.generate_csrf_token("session-1")

        result = security.validate_csrf_token(token, token)

        assert result is True

    def test_rejects_mismatched_tokens(self, test_settings: Settings) -> None:
        """Mismatched CSRF tokens fail validation."""
        security = SecurityService(test_settings)

        token1 = security.generate_csrf_token("session-1")
        token2 = security.generate_csrf_token("session-2")

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


class TestCSRFSignatureVerification:
    """Tests for CSRF HMAC signature verification."""

    def test_valid_signature_passes(self, test_settings: Settings) -> None:
        """Token verified against the same session_id succeeds."""
        security = SecurityService(test_settings)
        token = security.generate_csrf_token("my-session")

        assert security._verify_csrf_signature(token, "my-session") is True

    def test_wrong_session_rejected(self, test_settings: Settings) -> None:
        """Token signed for session A fails verification against session B."""
        security = SecurityService(test_settings)
        token = security.generate_csrf_token("session-a")

        assert security._verify_csrf_signature(token, "session-b") is False

    def test_unsigned_token_rejected(self, test_settings: Settings) -> None:
        """A plain random string without signature structure is rejected."""
        security = SecurityService(test_settings)

        assert security._verify_csrf_signature("plain-random-token", "session") is False

    def test_tampered_signature_rejected(self, test_settings: Settings) -> None:
        """Modifying the signature portion causes rejection."""
        security = SecurityService(test_settings)
        token = security.generate_csrf_token("session-x")

        nonce, sig = token.split(".", 1)
        tampered = f"{nonce}.{'a' * 64}"

        assert security._verify_csrf_signature(tampered, "session-x") is False


class TestCSRFExemptPaths:
    """Tests for CSRF exempt path configuration."""

    def test_exempt_paths_includes_login_and_register(
        self, test_settings: Settings
    ) -> None:
        """CSRF exempt paths include login and register."""
        security = SecurityService(test_settings)

        assert "/api/v1/auth/login" in security.CSRF_EXEMPT_PATHS
        assert "/api/v1/auth/register" in security.CSRF_EXEMPT_PATHS

    def test_logout_is_not_exempt(self, test_settings: Settings) -> None:
        """Logout is NOT exempt from CSRF validation."""
        security = SecurityService(test_settings)

        assert "/api/v1/auth/logout" not in security.CSRF_EXEMPT_PATHS

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
        """Valid signed CSRF tokens pass full request validation."""
        security = SecurityService(test_settings)
        access_token = "my-access-token-value"
        token = security.generate_csrf_token(access_token)
        req = make_request(
            "POST",
            "/api/v1/items",
            headers={"X-CSRF-Token": token},
            cookies={"access_token": access_token, "csrf_token": token},
        )

        assert security.validate_csrf_from_request(req) == token

    def test_forged_token_rejected(self, test_settings: Settings) -> None:
        """Unsigned token matching in header+cookie is rejected (signature check)."""
        security = SecurityService(test_settings)
        forged = "forged-random-value"
        req = make_request(
            "POST",
            "/api/v1/items",
            headers={"X-CSRF-Token": forged},
            cookies={"access_token": "some-jwt", "csrf_token": forged},
        )

        with pytest.raises(CSRFValidationError, match="signature invalid"):
            security.validate_csrf_from_request(req)

    def test_wrong_session_token_rejected(self, test_settings: Settings) -> None:
        """Token signed for one session rejected when presented with different access_token."""
        security = SecurityService(test_settings)
        token = security.generate_csrf_token("session-A-jwt")
        req = make_request(
            "POST",
            "/api/v1/items",
            headers={"X-CSRF-Token": token},
            cookies={"access_token": "session-B-jwt", "csrf_token": token},
        )

        with pytest.raises(CSRFValidationError, match="signature invalid"):
            security.validate_csrf_from_request(req)

    def test_logout_requires_csrf(self, test_settings: Settings) -> None:
        """POST to logout with authentication requires CSRF token."""
        security = SecurityService(test_settings)
        req = make_request(
            "POST",
            "/api/v1/auth/logout",
            cookies={"access_token": "tok"},
        )

        with pytest.raises(CSRFValidationError):
            security.validate_csrf_from_request(req)
