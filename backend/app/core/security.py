import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Request
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext

from app.core.metrics import SecurityMetrics
from app.domain.user import CSRFValidationError, InvalidCredentialsError
from app.settings import Settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/login")


class SecurityService:
    def __init__(self, settings: Settings, security_metrics: SecurityMetrics) -> None:
        self.settings = settings
        self._security_metrics = security_metrics
        # --8<-- [start:password_hashing]
        self.pwd_context = CryptContext(
            schemes=["bcrypt"],
            deprecated="auto",
            bcrypt__rounds=self.settings.BCRYPT_ROUNDS,
        )

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return self.pwd_context.verify(plain_password, hashed_password)  # type: ignore

    def get_password_hash(self, password: str) -> str:
        return self.pwd_context.hash(password)  # type: ignore
    # --8<-- [end:password_hashing]

    # --8<-- [start:create_access_token]
    def create_access_token(self, data: dict[str, Any], expires_delta: timedelta) -> str:
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + expires_delta
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, self.settings.SECRET_KEY, algorithm=self.settings.ALGORITHM)
        return encoded_jwt
    # --8<-- [end:create_access_token]

    def decode_token(self, token: str, *, allow_expired: bool = False) -> str:
        """Decode JWT and return the username (sub claim).

        Args:
            token: The JWT token string.
            allow_expired: If True, accept expired tokens (used for logout).
        """
        try:
            options = {"verify_exp": not allow_expired}
            payload = jwt.decode(
                token, self.settings.SECRET_KEY, algorithms=[self.settings.ALGORITHM], options=options,
            )
            username: str | None = payload.get("sub")
            if username is None:
                raise InvalidCredentialsError()
            return username
        except jwt.PyJWTError:
            raise InvalidCredentialsError() from None

    def generate_csrf_token(self, session_id: str) -> str:
        """Generate a signed CSRF token bound to the given session (access_token).

        Returns a token in the format ``{nonce}.{hmac_hex}`` so the server can
        later verify it was issued for the same session.
        """
        nonce = secrets.token_urlsafe(16)
        signature = self._sign_csrf(nonce, session_id)
        return f"{nonce}.{signature}"

    def _sign_csrf(self, nonce: str, session_id: str) -> str:
        return hmac.new(
            self.settings.SECRET_KEY.encode(),
            f"{nonce}:{session_id}".encode(),
            "sha256",
        ).hexdigest()

    def _verify_csrf_signature(self, token: str, session_id: str) -> bool:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return False
        nonce, signature = parts
        expected = self._sign_csrf(nonce, session_id)
        return hmac.compare_digest(signature, expected)

    # --8<-- [start:csrf_validation]
    def validate_csrf_token(self, header_token: str, cookie_token: str) -> bool:
        """Validate CSRF token using double-submit cookie pattern"""
        if not header_token or not cookie_token:
            return False
        # Constant-time comparison to prevent timing attacks
        return hmac.compare_digest(header_token, cookie_token)

    # Paths exempt from CSRF validation (auth handles its own security)
    CSRF_EXEMPT_PATHS: frozenset[str] = frozenset({
        "/api/v1/auth/login",
        "/api/v1/auth/register",
    })

    def validate_csrf_from_request(self, request: Request) -> str:
        """Validate CSRF token from HTTP request using double-submit cookie pattern.

        Returns:
            "skip" if validation was skipped (safe method, exempt path, or unauthenticated)
            The validated token string if validation passed

        Raises:
            CSRFValidationError: If token is missing or invalid
        """
        # Skip CSRF validation for safe methods
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return "skip"

        # Skip CSRF validation for auth endpoints
        if request.url.path in self.CSRF_EXEMPT_PATHS:
            return "skip"

        # Skip CSRF validation for non-API endpoints (health, metrics, etc.)
        if not request.url.path.startswith("/api/"):
            return "skip"

        # Check if user is authenticated first (has access_token cookie)
        access_token = request.cookies.get("access_token")
        if not access_token:
            # If not authenticated, skip CSRF validation (auth will be handled by other dependencies)
            return "skip"

        # Get CSRF token from header and cookie
        header_token = request.headers.get("X-CSRF-Token")
        cookie_token = request.cookies.get("csrf_token", "")

        if not header_token:
            self._security_metrics.record_csrf_validation_failure("missing_header")
            raise CSRFValidationError("CSRF token missing from X-CSRF-Token header")

        if not self.validate_csrf_token(header_token, cookie_token):
            self._security_metrics.record_csrf_validation_failure("token_mismatch")
            raise CSRFValidationError("CSRF token invalid or does not match cookie")

        if not self._verify_csrf_signature(header_token, access_token):
            self._security_metrics.record_csrf_validation_failure("invalid_signature")
            raise CSRFValidationError("CSRF token signature invalid")

        return header_token
    # --8<-- [end:csrf_validation]
