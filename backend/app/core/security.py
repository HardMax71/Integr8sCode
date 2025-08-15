from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from fastapi import HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext

from app.config import get_settings
from app.schemas_pydantic.user import UserInDB, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/login")


def get_token_from_cookie(request: Request) -> str:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


class SecurityService:
    def __init__(self) -> None:
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        self.settings = get_settings()

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return self.pwd_context.verify(plain_password, hashed_password)  # type: ignore

    def get_password_hash(self, password: str) -> str:
        return self.pwd_context.hash(password)  # type: ignore

    def create_access_token(
            self, data: dict, expires_delta: Optional[timedelta] = None
    ) -> str:
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=15)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(
            to_encode, self.settings.SECRET_KEY, algorithm=self.settings.ALGORITHM
        )
        return encoded_jwt

    async def get_current_user(
            self,
            token: str,
            user_repo: Any,  # Avoid circular import by using Any
    ) -> UserInDB:
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        try:
            payload = jwt.decode(
                token, self.settings.SECRET_KEY, algorithms=[self.settings.ALGORITHM]
            )
            username: str = payload.get("sub")
            if username is None:
                raise credentials_exception
        except jwt.PyJWTError as e:
            raise credentials_exception from e
        user = await user_repo.get_user(username)
        if user is None:
            raise credentials_exception
        return user  # type: ignore[no-any-return]

    async def get_current_admin_user(
            self,
            token: str,
            user_repo: Any,  # Avoid circular import by using Any
    ) -> UserInDB:
        """Ensure current user has admin role"""
        # First get the current user
        current_user = await self.get_current_user(token, user_repo)

        # Then check if they have admin role
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions",
            )
        return current_user

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


security_service = SecurityService()


def validate_csrf_token(request: Request) -> str:
    """FastAPI dependency to validate CSRF token using double-submit cookie pattern"""
    # Skip CSRF validation for safe methods
    if request.method in ["GET", "HEAD", "OPTIONS"]:
        return "skip"

    # Skip CSRF validation for auth endpoints
    if request.url.path in ["/api/v1/login", "/api/v1/register", "/api/v1/logout"]:
        return "skip"

    # Skip CSRF validation for non-API endpoints
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing"
        )

    if not security_service.validate_csrf_token(header_token, cookie_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token invalid"
        )

    return header_token
