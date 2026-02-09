from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.domain.enums import UserRole
from app.domain.rate_limit import EndpointGroup, EndpointUsageStats, RateLimitAlgorithm


class UserBase(BaseModel):
    """Base user model with common fields"""

    username: str
    email: EmailStr
    role: UserRole = UserRole.USER
    is_active: bool = True

    model_config = ConfigDict(from_attributes=True)


class UserCreate(UserBase):
    """Model for creating a new user"""

    password: str = Field(..., min_length=8)

    model_config = ConfigDict(from_attributes=True)


class UserInDB(UserBase):
    """User model as stored in database (with hashed password)"""

    user_id: str = Field(default_factory=lambda: str(uuid4()))
    hashed_password: str
    is_superuser: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)


class UserUpdate(BaseModel):
    """Model for updating a user"""

    username: str | None = None
    email: EmailStr | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=8)

    model_config = ConfigDict(from_attributes=True)


class UserResponse(UserBase):
    """User model for API responses (without password)"""

    user_id: str
    role: UserRole
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime
    # Rate limit summary fields (optional, populated by admin endpoints)
    bypass_rate_limit: bool | None = None
    global_multiplier: float | None = None
    has_custom_limits: bool | None = None

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
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(
        from_attributes=True,
        arbitrary_types_allowed=True,
    )


class UserListResponse(BaseModel):
    """Response model for listing users"""

    users: list[UserResponse]
    total: int
    offset: int
    limit: int

    model_config = ConfigDict(from_attributes=True)


class PasswordResetRequest(BaseModel):
    """Request model for password reset"""

    new_password: str = Field(..., min_length=8, description="New password for the user")

    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    """Generic message response"""

    message: str

    model_config = ConfigDict(from_attributes=True)


class LoginResponse(BaseModel):
    """Response model for successful login"""

    message: str
    username: str
    role: UserRole
    csrf_token: str

    model_config = ConfigDict(from_attributes=True)




class DeleteUserResponse(BaseModel):
    """Response model for user deletion."""

    message: str
    user_deleted: bool
    executions: int = 0
    saved_scripts: int = 0
    notifications: int = 0
    user_settings: int = 0
    events: int = 0
    sagas: int = 0

    model_config = ConfigDict(from_attributes=True)


class RateLimitRuleResponse(BaseModel):
    """Response model for rate limit rule."""

    endpoint_pattern: str
    group: EndpointGroup
    requests: int
    window_seconds: int
    algorithm: RateLimitAlgorithm
    burst_multiplier: float = 1.5
    priority: int = 0
    enabled: bool = True

    model_config = ConfigDict(from_attributes=True)


class RateLimitRuleRequest(BaseModel):
    """Request model for rate limit rule."""

    endpoint_pattern: str
    group: EndpointGroup
    requests: int
    window_seconds: int
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.SLIDING_WINDOW
    burst_multiplier: float = 1.5
    priority: int = 0
    enabled: bool = True


class RateLimitUpdateRequest(BaseModel):
    """Request model for updating user rate limits."""

    bypass_rate_limit: bool = False
    global_multiplier: float = 1.0
    rules: list[RateLimitRuleRequest] = []
    notes: str | None = None


class UserRateLimitConfigResponse(BaseModel):
    """Response model for user rate limit config."""

    user_id: str
    bypass_rate_limit: bool
    global_multiplier: float
    rules: list[RateLimitRuleResponse]
    created_at: datetime | None = None
    updated_at: datetime | None = None
    notes: str | None = None

    model_config = ConfigDict(from_attributes=True)


class UserRateLimitsResponse(BaseModel):
    """Response model for user rate limits with usage stats."""

    user_id: str
    rate_limit_config: UserRateLimitConfigResponse | None = None
    current_usage: dict[str, EndpointUsageStats]

    model_config = ConfigDict(from_attributes=True)


class RateLimitUpdateResponse(BaseModel):
    """Response model for rate limit update."""

    user_id: str
    updated: bool
    config: UserRateLimitConfigResponse

    model_config = ConfigDict(from_attributes=True)
