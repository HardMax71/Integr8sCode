from datetime import timedelta
from typing import Dict, Union

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api.dependencies import get_current_user
from app.config import get_settings
from app.core.logging import logger
from app.core.security import security_service
from app.core.service_dependencies import UserRepositoryDep
from app.schemas_pydantic.user import UserCreate, UserInDB, UserResponse

router = APIRouter(prefix="/auth", tags=["authentication"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/login")
@limiter.limit("10/minute")
async def login(
        request: Request,
        response: Response,
        user_repo: UserRepositoryDep,
        form_data: OAuth2PasswordRequestForm = Depends(),
) -> Dict[str, str]:
    logger.info(
        "Login attempt",
        extra={
            "username": form_data.username,
            "client_ip": get_remote_address(request),
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
                "client_ip": get_remote_address(request),
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
                "client_ip": get_remote_address(request),
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
            "client_ip": get_remote_address(request),
            "user_agent": request.headers.get("user-agent"),
            "token_expires_in_minutes": settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        },
    )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security_service.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    csrf_token = security_service.generate_csrf_token()

    # Set httpOnly cookie for secure token storage
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # Convert to seconds
        httponly=True,
        secure=True,  # HTTPS only
        samesite="strict",  # CSRF protection
        path="/",
    )

    # Set CSRF token cookie (readable by JavaScript for header inclusion)
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=False,  # JavaScript needs to read this
        secure=True,
        samesite="strict",
        path="/",
    )

    return {
        "message": "Login successful",
        "username": user.username,
        "user_id": user.user_id,
        "role": user.role,
        "email": user.email,
        "csrf_token": csrf_token
    }


@router.post("/register", response_model=UserResponse)
@limiter.limit("5/minute")
async def register(
        request: Request,
        user: UserCreate,
        user_repo: UserRepositoryDep,
) -> UserResponse:
    logger.info(
        "Registration attempt",
        extra={
            "username": user.username,
            "client_ip": get_remote_address(request),
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
                "client_ip": get_remote_address(request),
                "user_agent": request.headers.get("user-agent"),
            },
        )
        raise HTTPException(status_code=400, detail="Username already registered")

    try:
        hashed_password = security_service.get_password_hash(user.password)
        db_user = UserInDB(
            **user.model_dump(),
            hashed_password=hashed_password
        )
        created_user = await user_repo.create_user(db_user)

        logger.info(
            "Registration successful",
            extra={
                "username": created_user.username,
                "client_ip": get_remote_address(request),
                "user_agent": request.headers.get("user-agent"),
            },
        )

        return UserResponse.model_validate(created_user.model_dump())

    except Exception as e:
        logger.error(
            f"Registration failed - database error: {str(e)}",
            extra={
                "username": user.username,
                "client_ip": get_remote_address(request),
                "user_agent": request.headers.get("user-agent"),
                "error_type": type(e).__name__,
                "error_detail": str(e),
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Error creating user") from e


@router.get("/verify-token")
@limiter.limit("30/minute")
async def verify_token(
        request: Request,
        current_user: UserResponse = Depends(get_current_user),
) -> Dict[str, Union[str, bool]]:
    logger.info(
        "Token verification attempt",
        extra={
            "username": current_user.username,
            "client_ip": get_remote_address(request),
            "endpoint": "/verify-token",
            "user_agent": request.headers.get("user-agent"),
        },
    )

    try:
        logger.info(
            "Token verification successful",
            extra={
                "username": current_user.username,
                "client_ip": get_remote_address(request),
                "user_agent": request.headers.get("user-agent"),
            },
        )
        # Return existing CSRF token from cookie
        csrf_token = request.cookies.get("csrf_token", "")

        return {
            "valid": True,
            "username": current_user.username,
            "user_id": current_user.user_id,
            "role": current_user.role,
            "email": current_user.email,
            "csrf_token": csrf_token
        }

    except Exception as e:
        logger.error(
            "Token verification failed",
            extra={
                "client_ip": get_remote_address(request),
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


@router.get("/me", response_model=UserResponse)
@limiter.limit("30/minute")
async def get_current_user_info(
        request: Request,
        current_user: UserResponse = Depends(get_current_user),
) -> UserResponse:
    logger.info(
        "Get current user info",
        extra={
            "username": current_user.username,
            "client_ip": get_remote_address(request),
            "endpoint": "/me",
            "user_agent": request.headers.get("user-agent"),
        },
    )

    return current_user


@router.post("/logout")
@limiter.limit("10/minute")
async def logout(
        request: Request,
        response: Response,
) -> Dict[str, str]:
    logger.info(
        "Logout attempt",
        extra={
            "client_ip": get_remote_address(request),
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
            "client_ip": get_remote_address(request),
            "user_agent": request.headers.get("user-agent"),
        },
    )

    return {"message": "Logout successful"}
