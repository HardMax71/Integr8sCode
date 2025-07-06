from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from app.config import get_settings
from app.db.repositories.user_repository import UserRepository, get_user_repository
from app.schemas.user import UserInDB
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

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
        self.csrf_serializer = URLSafeTimedSerializer(
            secret_key=self.settings.SECRET_KEY,
            salt="csrf-token"
        )

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
            token: str = Depends(get_token_from_cookie),
            user_repo: UserRepository = Depends(get_user_repository),
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
        return user

    def generate_csrf_token(self, session_id: str) -> str:
        """Generate a CSRF token for the given session"""
        data = {
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat()
        }
        return self.csrf_serializer.dumps(data)

    def validate_csrf_token(self, token: str, session_id: str) -> bool:
        """Validate a CSRF token"""
        try:
            data = self.csrf_serializer.loads(token, max_age=3600)  # 1 hour
            return data.get("session_id") == session_id
        except (BadSignature, SignatureExpired):
            return False

    def get_session_id_from_request(self, request: Request) -> str:
        """Get session ID from request (using access token as session identifier)"""
        token = request.cookies.get("access_token")
        if token:
            return token[:32]  # Use first 32 chars as session ID
        
        # Fallback to client fingerprint
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        return f"{client_ip}:{user_agent}"[:32]


security_service = SecurityService()


def validate_csrf_token(request: Request) -> str:
    """FastAPI dependency to validate CSRF token"""
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
    
    # Get CSRF token from request
    csrf_token = request.headers.get("X-CSRF-Token")
    if not csrf_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing"
        )
    
    # Validate CSRF token
    session_id = security_service.get_session_id_from_request(request)
    if not security_service.validate_csrf_token(csrf_token, session_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token invalid"
        )
    
    return csrf_token
