from datetime import datetime, timedelta, timezone
from typing import Dict, Union
from uuid import uuid4

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm

from app.core.logging import logger
from app.core.security import security_service
from app.core.utils import get_client_ip
from app.db.repositories import UserRepository
from app.domain.user import User as DomainAdminUser
from app.schemas_pydantic.user import UserCreate, UserResponse
from app.services.auth_service import AuthService
from app.settings import get_settings

router = APIRouter(prefix="/auth",
                   tags=["authentication"],
                   route_class=DishkaRoute)


@router.post("/login")
async def login(
        request: Request,
        response: Response,
        user_repo: FromDishka[UserRepository],
        form_data: OAuth2PasswordRequestForm = Depends(),
) -> Dict[str, str]:
    logger.info(
        "Login attempt",
        extra={
            "username": form_data.username,
            "client_ip": get_client_ip(request),
            "endpoint": "/login",
            "user_agent": request.headers.get("user-agent"),
        },
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
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_settings()

    logger.info(
        "Login successful",
        extra={
            "username": user.username,
            "client_ip": get_client_ip(request),
            "user_agent": request.headers.get("user-agent"),
            "token_expires_in_minutes": settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        },
    )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security_service.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    csrf_token = security_service.generate_csrf_token()

    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # Convert to seconds
        httponly=True,
        secure=True,  # HTTPS only
        samesite="strict",  # CSRF protection
        path="/",
    )

    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=False,  # JavaScript needs to read this
        secure=True,
        samesite="strict",
        path="/",
    )

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"

    # Return minimal authentication response
    # Detailed user info should be fetched from GET /me endpoint
    return {
        "message": "Login successful",
        "username": user.username,
        "role": "admin" if user.is_superuser else "user",  # Coarse-grained role
        "csrf_token": csrf_token
    }


@router.post("/register", response_model=UserResponse)
async def register(
        request: Request,
        user: UserCreate,
        user_repo: FromDishka[UserRepository],
) -> UserResponse:
    logger.info(
        "Registration attempt",
        extra={
            "username": user.username,
            "client_ip": get_client_ip(request),
            "endpoint": "/register",
            "user_agent": request.headers.get("user-agent"),
        },
    )

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
        raise HTTPException(status_code=400, detail="Username already registered")

    try:
        hashed_password = security_service.get_password_hash(user.password)
        now = datetime.now(timezone.utc)
        domain_user = DomainAdminUser(
            user_id=str(uuid4()),
            username=user.username,
            email=str(user.email),
            role=user.role,
            is_active=True,
            is_superuser=False,
            hashed_password=hashed_password,
            created_at=now,
            updated_at=now,
        )
        created_user = await user_repo.create_user(domain_user)

        logger.info(
            "Registration successful",
            extra={
                "username": created_user.username,
                "client_ip": get_client_ip(request),
                "user_agent": request.headers.get("user-agent"),
            },
        )

        return UserResponse(
            user_id=created_user.user_id,
            username=created_user.username,
            email=created_user.email,
            role=created_user.role,
            is_superuser=created_user.is_superuser,
            created_at=created_user.created_at,
            updated_at=created_user.updated_at,
        )

    except Exception as e:
        logger.error(
            f"Registration failed - database error: {str(e)}",
            extra={
                "username": user.username,
                "client_ip": get_client_ip(request),
                "user_agent": request.headers.get("user-agent"),
                "error_type": type(e).__name__,
                "error_detail": str(e),
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Error creating user") from e


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
        request: Request,
        response: Response,
        auth_service: FromDishka[AuthService],
) -> UserResponse:
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
    
    return current_user


@router.get("/verify-token")
async def verify_token(
        request: Request,
        auth_service: FromDishka[AuthService],
) -> Dict[str, Union[str, bool]]:
    current_user = await auth_service.get_current_user(request)
    logger.info(
        "Token verification attempt",
        extra={
            "username": current_user.username,
            "client_ip": get_client_ip(request),
            "endpoint": "/verify-token",
            "user_agent": request.headers.get("user-agent"),
        },
    )

    try:
        logger.info(
            "Token verification successful",
            extra={
                "username": current_user.username,
                "client_ip": get_client_ip(request),
                "user_agent": request.headers.get("user-agent"),
            },
        )
        # Return existing CSRF token from cookie
        csrf_token = request.cookies.get("csrf_token", "")

        return {
            "valid": True,
            "username": current_user.username,
            "role": "admin" if current_user.is_superuser else "user",  # Coarse-grained role
            "csrf_token": csrf_token
        }

    except Exception as e:
        logger.error(
            "Token verification failed",
            extra={
                "client_ip": get_client_ip(request),
                "user_agent": request.headers.get("user-agent"),
                "error_type": type(e).__name__,
                "error_detail": str(e),
            },
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e




@router.post("/logout")
async def logout(
        request: Request,
        response: Response,
) -> Dict[str, str]:
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

    return {"message": "Logout successful"}
