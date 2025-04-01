from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from app.config import get_settings
from app.db.repositories.user_repository import UserRepository, get_user_repository
from app.schemas.user import UserInDB
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/login")


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
            token: str = Depends(oauth2_scheme),
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


security_service = SecurityService()
