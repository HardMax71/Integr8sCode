import logging
from datetime import timedelta

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm

from app.core.security import SecurityService
from app.core.utils import get_client_ip
from app.db.repositories import UserRepository
from app.domain.enums import UserRole
from app.domain.user import DomainUserCreate
from app.schemas_pydantic.common import ErrorResponse
from app.schemas_pydantic.user import (
    LoginResponse,
    MessageResponse,
    UserCreate,
    UserResponse,
)
from app.services.auth_service import AuthService
from app.services.login_lockout import LoginLockoutService
from app.services.runtime_settings import RuntimeSettingsLoader

router = APIRouter(prefix="/auth", tags=["authentication"], route_class=DishkaRoute)


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Invalid username or password"},
        423: {"model": ErrorResponse, "description": "Account temporarily locked"},
    },
)
async def login(
    request: Request,
    response: Response,
    user_repo: FromDishka[UserRepository],
    security_service: FromDishka[SecurityService],
    runtime_settings: FromDishka[RuntimeSettingsLoader],
    lockout_service: FromDishka[LoginLockoutService],
    logger: FromDishka[logging.Logger],
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> LoginResponse:
    """Authenticate and receive session cookies."""
    logger.info(
        "Login attempt",
        extra={
            "username": form_data.username,
            "client_ip": get_client_ip(request),
            "endpoint": "/login",
            "user_agent": request.headers.get("user-agent"),
        },
    )

    if await lockout_service.check_locked(form_data.username):
        raise HTTPException(
            status_code=423,
            detail="Account temporarily locked due to too many failed attempts",
        )

    user = await user_repo.get_user(form_data.username)

    if not user:
        logger.warning(
            "Login failed - user not found",
            extra={
                "username": form_data.username,
                "client_ip": get_client_ip(request),
                "user_agent": request.headers.get("user-agent"),
            },
        )
        locked = await lockout_service.record_failed_attempt(form_data.username)
        if locked:
            raise HTTPException(
                status_code=423,
                detail="Account locked due to too many failed attempts",
            )
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not security_service.verify_password(form_data.password, user.hashed_password):
        logger.warning(
            "Login failed - invalid password",
            extra={
                "username": form_data.username,
                "client_ip": get_client_ip(request),
                "user_agent": request.headers.get("user-agent"),
            },
        )
        locked = await lockout_service.record_failed_attempt(form_data.username)
        if locked:
            raise HTTPException(
                status_code=423,
                detail="Account locked due to too many failed attempts",
            )
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    await lockout_service.clear_attempts(form_data.username)

    effective = await runtime_settings.get_effective_settings()
    session_timeout = effective.session_timeout_minutes

    logger.info(
        "Login successful",
        extra={
            "username": user.username,
            "client_ip": get_client_ip(request),
            "user_agent": request.headers.get("user-agent"),
            "token_expires_in_minutes": session_timeout,
        },
    )

    access_token_expires = timedelta(minutes=session_timeout)
    access_token = security_service.create_access_token(data={"sub": user.username}, expires_delta=access_token_expires)

    csrf_token = security_service.generate_csrf_token(access_token)

    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=session_timeout * 60,  # Convert to seconds
        httponly=True,
        secure=True,  # HTTPS only
        samesite="strict",  # CSRF protection
        path="/",
    )

    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        max_age=session_timeout * 60,
        httponly=False,  # JavaScript needs to read this
        secure=True,
        samesite="strict",
        path="/",
    )

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"

    return LoginResponse(
        message="Login successful",
        username=user.username,
        role=user.role,
        csrf_token=csrf_token,
    )


@router.post(
    "/register",
    response_model=UserResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Password too short"},
        409: {"model": ErrorResponse, "description": "User already exists"},
    },
)
async def register(
    request: Request,
    user: UserCreate,
    user_repo: FromDishka[UserRepository],
    security_service: FromDishka[SecurityService],
    runtime_settings: FromDishka[RuntimeSettingsLoader],
    logger: FromDishka[logging.Logger],
) -> UserResponse:
    """Register a new user account."""
    logger.info(
        "Registration attempt",
        extra={
            "username": user.username,
            "client_ip": get_client_ip(request),
            "endpoint": "/register",
            "user_agent": request.headers.get("user-agent"),
        },
    )

    effective = await runtime_settings.get_effective_settings()
    min_len = effective.password_min_length
    if len(user.password) < min_len:
        raise HTTPException(status_code=400, detail=f"Password must be at least {min_len} characters")

    db_user = await user_repo.get_user(user.username)
    if db_user:
        logger.warning(
            "Registration failed - username taken",
            extra={
                "username": user.username,
                "client_ip": get_client_ip(request),
                "user_agent": request.headers.get("user-agent"),
            },
        )
        raise HTTPException(status_code=409, detail="Username already registered")

    hashed_password = security_service.get_password_hash(user.password)
    create_data = DomainUserCreate(
        username=user.username,
        email=user.email,
        hashed_password=hashed_password,
        role=UserRole.USER,
        is_active=True,
        is_superuser=False,
    )
    created_user = await user_repo.create_user(create_data)

    logger.info(
        "Registration successful",
        extra={
            "username": created_user.username,
            "client_ip": get_client_ip(request),
            "user_agent": request.headers.get("user-agent"),
        },
    )

    return UserResponse.model_validate(created_user)


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    request: Request,
    response: Response,
    auth_service: FromDishka[AuthService],
    logger: FromDishka[logging.Logger],
) -> UserResponse:
    """Get the authenticated user's profile."""
    current_user = await auth_service.get_current_user(request)

    logger.info(
        "User profile request",
        extra={
            "username": current_user.username,
            "client_ip": get_client_ip(request),
            "endpoint": "/me",
        },
    )

    # Set cache control headers
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"

    return UserResponse.model_validate(current_user)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
    logger: FromDishka[logging.Logger],
) -> MessageResponse:
    """Log out and clear session cookies."""
    logger.info(
        "Logout attempt",
        extra={
            "client_ip": get_client_ip(request),
            "endpoint": "/logout",
            "user_agent": request.headers.get("user-agent"),
        },
    )

    # Clear the httpOnly cookie
    response.delete_cookie(
        key="access_token",
        path="/",
    )

    # Clear the CSRF cookie
    response.delete_cookie(
        key="csrf_token",
        path="/",
    )

    logger.info(
        "Logout successful",
        extra={
            "client_ip": get_client_ip(request),
            "user_agent": request.headers.get("user-agent"),
        },
    )

    return MessageResponse(message="Logout successful")
