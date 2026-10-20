from dataclasses import dataclass
from typing import TypedDict

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


@dataclass
class UserDeleteResult:
    """Domain result for user deletion."""

    user_deleted: bool
    executions: int = 0
    saved_scripts: int = 0
    notifications: int = 0
    user_settings: int = 0
    events: int = 0
    sagas: int = 0


@dataclass
class LoginResult:
    """Result of a successful login."""

    username: str
    role: UserRole
    access_token: str
    csrf_token: str
    session_timeout_minutes: int


class UserChanges(TypedDict, total=False):
    """Fields an admin update sets; a missing key keeps the stored value."""

    username: str
    email: str
    role: UserRole
    is_active: bool
    hashed_password: str
