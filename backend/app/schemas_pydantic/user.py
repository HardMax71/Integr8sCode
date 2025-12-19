from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.domain.enums.user import UserRole


class UserBase(BaseModel):
    """Base user model with common fields"""
    username: str
    email: EmailStr
    role: UserRole = UserRole.USER
    is_active: bool = True

    model_config = ConfigDict(
        from_attributes=True
    )


class UserCreate(UserBase):
    """Model for creating a new user"""
    password: str = Field(..., min_length=8)

    model_config = ConfigDict(
        from_attributes=True
    )


class UserInDB(UserBase):
    """User model as stored in database (with hashed password)"""
    user_id: str = Field(default_factory=lambda: str(uuid4()))
    hashed_password: str
    is_superuser: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(
        from_attributes=True,
        arbitrary_types_allowed=True
    )


class UserUpdate(BaseModel):
    """Model for updating a user"""
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=8)

    model_config = ConfigDict(
        from_attributes=True
    )


class UserResponse(UserBase):
    """User model for API responses (without password)"""
    user_id: str
    is_superuser: bool = False
    created_at: datetime
    updated_at: datetime
    # Rate limit summary fields (optional, populated by admin endpoints)
    bypass_rate_limit: Optional[bool] = None
    global_multiplier: Optional[float] = None
    has_custom_limits: Optional[bool] = None

    model_config = ConfigDict(
        from_attributes=True,
    )


class User(BaseModel):
    """User model for internal service use (without sensitive data)"""
    user_id: str
    username: str
    email: EmailStr
    role: UserRole = UserRole.USER
    is_active: bool = True
    is_superuser: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(
        from_attributes=True,
        arbitrary_types_allowed=True,
    )

    @classmethod
    def from_response(cls, user_response: UserResponse) -> "User":
        """Create User from UserResponse"""
        return cls(
            user_id=user_response.user_id,
            username=user_response.username,
            email=user_response.email,
            role=user_response.role,
            is_active=user_response.is_active,
            is_superuser=user_response.is_superuser,
            created_at=user_response.created_at,
            updated_at=user_response.updated_at
        )


class UserListResponse(BaseModel):
    """Response model for listing users"""
    users: List[UserResponse]
    total: int
    offset: int
    limit: int

    model_config = ConfigDict(
        from_attributes=True
    )


class PasswordResetRequest(BaseModel):
    """Request model for password reset"""
    new_password: str = Field(..., min_length=8, description="New password for the user")

    model_config = ConfigDict(
        from_attributes=True
    )


class MessageResponse(BaseModel):
    """Generic message response"""
    message: str

    model_config = ConfigDict(
        from_attributes=True
    )


class LoginResponse(BaseModel):
    """Response model for successful login"""
    message: str
    username: str
    role: str
    csrf_token: str

    model_config = ConfigDict(from_attributes=True)


class TokenValidationResponse(BaseModel):
    """Response model for token validation"""
    valid: bool
    username: str
    role: str
    csrf_token: str

    model_config = ConfigDict(from_attributes=True)
