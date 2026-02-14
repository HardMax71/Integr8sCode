from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.utils import StringEnum
from app.domain.enums import UserRole


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


