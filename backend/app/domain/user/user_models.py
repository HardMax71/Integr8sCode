import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.utils import StringEnum
from app.domain.enums.user import UserRole

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


class UserSearchFilter(BaseModel):
    """User search filter criteria."""

    model_config = ConfigDict(from_attributes=True)

    search_text: str | None = None
    role: UserRole | None = None


class User(BaseModel):
    """User domain model."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    username: str
    email: str
    role: UserRole
    is_active: bool
    is_superuser: bool
    hashed_password: str
    created_at: datetime
    updated_at: datetime
    # Rate limit summary (optional, populated by admin service)
    bypass_rate_limit: bool | None = None
    global_multiplier: float | None = None
    has_custom_limits: bool | None = None


class UserUpdate(BaseModel):
    """User update domain model."""

    model_config = ConfigDict(from_attributes=True)

    username: str | None = None
    email: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = None

    def has_updates(self) -> bool:
        return any(
            [
                self.username is not None,
                self.email is not None,
                self.role is not None,
                self.is_active is not None,
                self.password is not None,
            ]
        )


class UserListResult(BaseModel):
    """Result of listing users."""

    model_config = ConfigDict(from_attributes=True)

    users: list[User]
    total: int
    offset: int
    limit: int


class PasswordReset(BaseModel):
    """Password reset domain model."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    new_password: str

    def is_valid(self) -> bool:
        return bool(self.user_id and self.new_password and len(self.new_password) >= 8)


class UserCreation(BaseModel):
    """User creation domain model (API-facing, with plain password)."""

    model_config = ConfigDict(from_attributes=True)

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
                EMAIL_PATTERN.match(self.email) is not None,  # Proper email validation
            ]
        )


class DomainUserCreate(BaseModel):
    """User creation data for repository (with hashed password)."""

    model_config = ConfigDict(from_attributes=True)

    username: str
    email: str
    hashed_password: str
    role: UserRole = UserRole.USER
    is_active: bool = True
    is_superuser: bool = False


class DomainUserUpdate(BaseModel):
    """User update data for repository (with hashed password)."""

    model_config = ConfigDict(from_attributes=True)

    username: str | None = None
    email: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    hashed_password: str | None = None


class UserDeleteResult(BaseModel):
    """Result of deleting a user and optionally cascading to related data."""

    model_config = ConfigDict(from_attributes=True)

    user_deleted: bool
    executions: int = 0
    saved_scripts: int = 0
    notifications: int = 0
    user_settings: int = 0
    events: int = 0
    sagas: int = 0
