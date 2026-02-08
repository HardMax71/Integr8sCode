from datetime import datetime, timezone
from uuid import uuid4

from beanie import Document, Indexed
from pydantic import ConfigDict, EmailStr, Field

from app.domain.enums import UserRole


class UserDocument(Document):
    """User document as stored in database (with hashed password).

    Copied from UserInDB schema.
    """

    # From UserBase
    username: Indexed(str, unique=True)  # type: ignore[valid-type]
    email: Indexed(EmailStr, unique=True)  # type: ignore[valid-type]
    role: UserRole = UserRole.USER
    is_active: bool = True

    # From UserInDB
    user_id: Indexed(str, unique=True) = Field(default_factory=lambda: str(uuid4()))  # type: ignore[valid-type]
    hashed_password: str
    is_superuser: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Activity tracking
    last_login: datetime | None = None
    last_activity: datetime | None = None

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    class Settings:
        name = "users"
        use_state_management = True
