"""Domain models for admin user management.

This module provides strongly-typed domain models for user operations
to replace Dict[str, Any] usage throughout the admin users repository.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Dict, List, Optional


class UserFields(StrEnum):
    """Database field names for users collection."""
    USER_ID = "user_id"
    USERNAME = "username"
    EMAIL = "email"
    ROLE = "role"
    IS_ACTIVE = "is_active"
    IS_SUPERUSER = "is_superuser"
    HASHED_PASSWORD = "hashed_password"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class UserRole(StrEnum):
    """User roles in the system."""
    USER = "user"
    ADMIN = "admin"
    MODERATOR = "moderator"


class UserFilterType(StrEnum):
    """Types of user filters."""
    USERNAME = "username"
    EMAIL = "email"
    ROLE = "role"


@dataclass
class UserSearchFilter:
    """User search filter criteria."""
    search_text: Optional[str] = None
    role: Optional[UserRole] = None

    def to_query(self) -> Dict[str, Any]:
        """Convert to MongoDB query."""
        query: Dict[str, Any] = {}

        if self.search_text:
            query["$or"] = [
                {UserFields.USERNAME: {"$regex": self.search_text, "$options": "i"}},
                {UserFields.EMAIL: {"$regex": self.search_text, "$options": "i"}}
            ]

        if self.role:
            query[UserFields.ROLE] = self.role.value

        return query


@dataclass
class User:
    """User domain model."""
    user_id: str
    username: str
    email: str
    role: UserRole
    is_active: bool
    is_superuser: bool
    hashed_password: str
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB."""
        return {
            UserFields.USER_ID: self.user_id,
            UserFields.USERNAME: self.username,
            UserFields.EMAIL: self.email,
            UserFields.ROLE: self.role.value,
            UserFields.IS_ACTIVE: self.is_active,
            UserFields.IS_SUPERUSER: self.is_superuser,
            UserFields.HASHED_PASSWORD: self.hashed_password,
            UserFields.CREATED_AT: self.created_at,
            UserFields.UPDATED_AT: self.updated_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "User":
        """Create from MongoDB document."""
        return cls(
            user_id=data.get(UserFields.USER_ID, ""),
            username=data.get(UserFields.USERNAME, ""),
            email=data.get(UserFields.EMAIL, ""),
            role=UserRole(data.get(UserFields.ROLE, UserRole.USER)),
            is_active=data.get(UserFields.IS_ACTIVE, True),
            is_superuser=data.get(UserFields.IS_SUPERUSER, False),
            hashed_password=data.get(UserFields.HASHED_PASSWORD, ""),
            created_at=data.get(UserFields.CREATED_AT, datetime.now(timezone.utc)),
            updated_at=data.get(UserFields.UPDATED_AT, datetime.now(timezone.utc))
        )

    def to_response_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response (without password)."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "role": self.role.value,
            "is_active": self.is_active,
            "is_superuser": self.is_superuser,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }


@dataclass
class UserUpdate:
    """User update domain model."""
    username: Optional[str] = None
    email: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

    def to_update_dict(self) -> Dict[str, Any]:
        """Convert to update dictionary for MongoDB."""
        update_dict: Dict[str, Any] = {}

        if self.username is not None:
            update_dict[UserFields.USERNAME] = self.username
        if self.email is not None:
            update_dict[UserFields.EMAIL] = self.email
        if self.role is not None:
            update_dict[UserFields.ROLE] = self.role.value
        if self.is_active is not None:
            update_dict[UserFields.IS_ACTIVE] = self.is_active

        # Password will be handled separately in repository
        return update_dict

    def has_updates(self) -> bool:
        """Check if there are any updates."""
        return any([
            self.username is not None,
            self.email is not None,
            self.role is not None,
            self.is_active is not None,
            self.password is not None
        ])


@dataclass
class UserListResult:
    """Result of listing users."""
    users: List[User]
    total: int
    offset: int
    limit: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "users": [user.to_response_dict() for user in self.users],
            "total": self.total,
            "offset": self.offset,
            "limit": self.limit
        }


@dataclass
class PasswordReset:
    """Password reset domain model."""
    user_id: str
    new_password: str

    def is_valid(self) -> bool:
        """Validate password reset."""
        return bool(self.user_id and self.new_password and len(self.new_password) >= 8)


@dataclass
class UserCreation:
    """User creation domain model."""
    username: str
    email: str
    password: str
    role: UserRole = UserRole.USER
    is_active: bool = True
    is_superuser: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB (without password)."""
        return {
            UserFields.USERNAME: self.username,
            UserFields.EMAIL: self.email,
            UserFields.ROLE: self.role.value,
            UserFields.IS_ACTIVE: self.is_active,
            UserFields.IS_SUPERUSER: self.is_superuser,
            UserFields.CREATED_AT: datetime.now(timezone.utc),
            UserFields.UPDATED_AT: datetime.now(timezone.utc)
        }

    def is_valid(self) -> bool:
        """Validate user creation data."""
        return all([
            self.username,
            self.email,
            self.password and len(self.password) >= 8,
            "@" in self.email  # Basic email validation
        ])
