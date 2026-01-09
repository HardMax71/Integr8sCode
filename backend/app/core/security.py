from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Request
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext

from app.domain.user import AuthenticationRequiredError, CSRFValidationError, InvalidCredentialsError
from app.domain.user import User as DomainAdminUser
from app.settings import Settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/login")


def get_token_from_cookie(request: Request) -> str:
    token = request.cookies.get("access_token")
    if not token:
        raise AuthenticationRequiredError("Authentication token not found")
    return token


class SecurityService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.pwd_context = CryptContext(
            schemes=["bcrypt"],
            deprecated="auto",
            bcrypt__rounds=self.settings.BCRYPT_ROUNDS,
        )

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return self.pwd_context.verify(plain_password, hashed_password)  # type: ignore

    def get_password_hash(self, password: str) -> str:
        return self.pwd_context.hash(password)  # type: ignore

    def create_access_token(self, data: dict[str, Any], expires_delta: timedelta) -> str:
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + expires_delta
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, self.settings.SECRET_KEY, algorithm=self.settings.ALGORITHM)
        return encoded_jwt

    async def get_current_user(
        self,
        token: str,
        user_repo: Any,  # Avoid circular import by using Any
    ) -> DomainAdminUser:
        try:
            payload = jwt.decode(token, self.settings.SECRET_KEY, algorithms=[self.settings.ALGORITHM])
            username: str = payload.get("sub")
            if username is None:
                raise InvalidCredentialsError()
        except jwt.PyJWTError as e:
            raise InvalidCredentialsError() from e
        user = await user_repo.get_user(username)
        if user is None:
            raise InvalidCredentialsError()
        return user  # type: ignore[no-any-return]

    def generate_csrf_token(self) -> str:
        """Generate a CSRF token using secure random"""
        import secrets

        return secrets.token_urlsafe(32)

    def validate_csrf_token(self, header_token: str, cookie_token: str) -> bool:
        """Validate CSRF token using double-submit cookie pattern"""
        if not header_token or not cookie_token:
            return False
        # Constant-time comparison to prevent timing attacks
        import hmac

        return hmac.compare_digest(header_token, cookie_token)

    # Paths exempt from CSRF validation (auth handles its own security)
    CSRF_EXEMPT_PATHS: frozenset[str] = frozenset({
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/logout",
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
            raise CSRFValidationError("CSRF token missing from X-CSRF-Token header")

        if not self.validate_csrf_token(header_token, cookie_token):
            raise CSRFValidationError("CSRF token invalid or does not match cookie")

        return header_token
