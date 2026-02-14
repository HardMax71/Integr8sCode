import re
from dataclasses import dataclass
from datetime import datetime

from app.core.utils import StringEnum
from app.domain.enums import UserRole

EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


class UserFields(StringEnum):
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


class UserFilterType(StringEnum):
    """Types of user filters."""

    USERNAME = "username"
    EMAIL = "email"
    ROLE = "role"


@dataclass
class UserSearchFilter:
    """User search filter criteria."""

    search_text: str | None = None
    role: UserRole | None = None


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
    bypass_rate_limit: bool | None = None
    global_multiplier: float | None = None
    has_custom_limits: bool | None = None


@dataclass
class UserUpdate:
    """User update domain model."""

    username: str | None = None
    email: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = None


@dataclass
class UserListResult:
    """Result of listing users."""

    users: list[User]
    total: int
    offset: int
    limit: int


@dataclass
class PasswordReset:
    """Password reset domain model."""

    user_id: str
    new_password: str

    def is_valid(self) -> bool:
        return bool(self.user_id and self.new_password and len(self.new_password) >= 8)


@dataclass
class UserCreation:
    """User creation domain model (API-facing, with plain password)."""

    username: str
    email: str
    password: str
    role: UserRole = UserRole.USER
    is_active: bool = True
    is_superuser: bool = False

    def is_valid(self) -> bool:
        return all(
            [
                self.username,
                self.email,
                self.password and len(self.password) >= 8,
                EMAIL_PATTERN.match(self.email) is not None,
            ]
        )


@dataclass
class DomainUserCreate:
    """User creation data for repository (with hashed password)."""

    username: str
    email: str
    hashed_password: str
    role: UserRole = UserRole.USER
    is_active: bool = True
    is_superuser: bool = False


@dataclass
class DomainUserUpdate:
    """User update data for repository (with hashed password)."""

    username: str | None = None
    email: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    hashed_password: str | None = None


@dataclass
class UserDeleteResult:
    """Result of deleting a user and optionally cascading to related data."""

    user_deleted: bool
    executions: int = 0
    saved_scripts: int = 0
    notifications: int = 0
    user_settings: int = 0
    events: int = 0
    sagas: int = 0
