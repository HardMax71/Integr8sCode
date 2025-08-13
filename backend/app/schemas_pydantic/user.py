"""User models for authentication and user management"""

from datetime import datetime, timezone
from enum import StrEnum
from typing import List
from uuid import uuid4

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRole(StrEnum):
    """User roles in the system"""
    USER = "user"
    ADMIN = "admin"
    MODERATOR = "moderator"


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
    username: str | None = None
    email: EmailStr | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=8)

    model_config = ConfigDict(
        from_attributes=True
    )


class UserResponse(UserBase):
    """User model for API responses (without password)"""
    user_id: str
    is_superuser: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={
            ObjectId: str
        }
    )


class User(BaseModel):
    """User model for internal service use (without sensitive data)"""
    user_id: str
    username: str
    email: EmailStr
    role: UserRole = UserRole.USER
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(
        from_attributes=True,
        arbitrary_types_allowed=True,
        json_encoders={
            ObjectId: str
        }
    )

    @classmethod
    def from_response(cls, user_response: UserResponse) -> "User":
        """Create User from UserResponse"""
        return cls(
            user_id=user_response.user_id,
            username=user_response.username,
            email=user_response.email,
            role=user_response.role,
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
