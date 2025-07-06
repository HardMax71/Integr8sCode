from datetime import timedelta
from typing import Dict, Union

from app.config import get_settings
from app.core.logging import logger
from app.core.security import security_service
from app.db.repositories.user_repository import UserRepository, get_user_repository
from app.schemas.user import UserCreate, UserInDB, UserResponse
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter
from slowapi.util import get_remote_address

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/login")
async def login(
        request: Request,
        response: Response,
        form_data: OAuth2PasswordRequestForm = Depends(),
        user_repo: UserRepository = Depends(get_user_repository),
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
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security_service.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    logger.info(
        "Login successful",
        extra={
            "username": user.username,
            "client_ip": get_remote_address(request),
            "user_agent": request.headers.get("user-agent"),
            "token_expires_in_minutes": settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        },
    )

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

    # Generate CSRF token for the session
    session_id = security_service.get_session_id_from_request(request)
    csrf_token = security_service.generate_csrf_token(session_id)
    
    return {"message": "Login successful", "username": user.username, "csrf_token": csrf_token}


@router.post("/register", response_model=UserResponse)
async def register(
        request: Request,
        user: UserCreate,
        user_repo: UserRepository = Depends(get_user_repository),
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
        db_user = UserInDB(**user.dict(), hashed_password=hashed_password)
        created_user = await user_repo.create_user(db_user)

        logger.info(
            "Registration successful",
            extra={
                "username": created_user.username,
                "client_ip": get_remote_address(request),
                "user_agent": request.headers.get("user-agent"),
            },
        )

        return UserResponse.model_validate(created_user)

    except Exception as e:
        logger.error(
            "Registration failed - database error",
            extra={
                "username": user.username,
                "client_ip": get_remote_address(request),
                "user_agent": request.headers.get("user-agent"),
                "error_type": type(e).__name__,
                "error_detail": str(e),
            },
        )
        raise HTTPException(status_code=500, detail="Error creating user") from e


@router.get("/verify-token")
async def verify_token(
        request: Request,
        current_user: UserInDB = Depends(security_service.get_current_user),
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
        # Generate fresh CSRF token for authenticated session
        session_id = security_service.get_session_id_from_request(request)
        csrf_token = security_service.generate_csrf_token(session_id)
        
        return {"valid": True, "username": current_user.username, "csrf_token": csrf_token}

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


@router.post("/logout")
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
        secure=True,
        httponly=True,
        samesite="strict",
    )

    logger.info(
        "Logout successful",
        extra={
            "client_ip": get_remote_address(request),
            "user_agent": request.headers.get("user-agent"),
        },
    )

    return {"message": "Logout successful"}
