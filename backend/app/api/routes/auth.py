import structlog
from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import OAuth2PasswordRequestForm

from app.core.utils import get_client_ip
from app.schemas_pydantic.common import ErrorResponse
from app.schemas_pydantic.user import (
    LoginResponse,
    MessageResponse,
    UserCreate,
    UserResponse,
)
from app.services.auth_service import AuthService

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
    auth_service: FromDishka[AuthService],
    logger: FromDishka[structlog.stdlib.BoundLogger],
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> LoginResponse:
    """Authenticate and receive session cookies."""
    logger.info(
        "Login attempt",
        username=form_data.username,
        client_ip=get_client_ip(request),
        endpoint="/login",
        user_agent=request.headers.get("user-agent"),
    )

    result = await auth_service.login(
        form_data.username,
        form_data.password,
        get_client_ip(request),
        request.headers.get("user-agent"),
    )

    # --8<-- [start:login_cookies]
    response.set_cookie(
        key="access_token",
        value=result.access_token,
        max_age=result.session_timeout_minutes * 60,
        httponly=True,
        secure=True,  # HTTPS only
        samesite="strict",  # CSRF protection
        path="/",
    )

    response.set_cookie(
        key="csrf_token",
        value=result.csrf_token,
        max_age=result.session_timeout_minutes * 60,
        httponly=False,  # JavaScript needs to read this
        secure=True,
        samesite="strict",
        path="/",
    )
    # --8<-- [end:login_cookies]

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"

    return LoginResponse(
        message="Login successful",
        username=result.username,
        role=result.role,
        csrf_token=result.csrf_token,
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
    auth_service: FromDishka[AuthService],
    logger: FromDishka[structlog.stdlib.BoundLogger],
) -> UserResponse:
    """Register a new user account."""
    logger.info(
        "Registration attempt",
        username=user.username,
        client_ip=get_client_ip(request),
        endpoint="/register",
        user_agent=request.headers.get("user-agent"),
    )

    created_user = await auth_service.register(
        user.username,
        user.email,
        user.password,
        get_client_ip(request),
        request.headers.get("user-agent"),
    )

    return UserResponse.model_validate(created_user)


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    request: Request,
    response: Response,
    auth_service: FromDishka[AuthService],
    logger: FromDishka[structlog.stdlib.BoundLogger],
) -> UserResponse:
    """Get the authenticated user's profile."""
    current_user = await auth_service.get_current_user(request)

    logger.info(
        "User profile request",
        username=current_user.username,
        client_ip=get_client_ip(request),
        endpoint="/me",
    )

    # Set cache control headers
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"

    return UserResponse.model_validate(current_user)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
    auth_service: FromDishka[AuthService],
    logger: FromDishka[structlog.stdlib.BoundLogger],
) -> MessageResponse:
    """Log out and clear session cookies."""
    logger.info(
        "Logout attempt",
        client_ip=get_client_ip(request),
        endpoint="/logout",
        user_agent=request.headers.get("user-agent"),
    )

    token = request.cookies.get("access_token")
    await auth_service.publish_logout_event(token)

    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="csrf_token", path="/")

    logger.info(
        "Logout successful",
        client_ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return MessageResponse(message="Logout successful")
