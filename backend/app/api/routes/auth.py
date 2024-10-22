from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta
from app.core.security import security_service
from app.config import get_settings
from app.db.repositories.user_repository import UserRepository, get_user_repository
from app.models.user import UserCreate, UserInDB
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.logging import logger

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

@router.post("/login")
@limiter.limit("20/minute")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    user_repo: UserRepository = Depends(get_user_repository)
):
    logger.info(
        "Login attempt",
        extra={
            "username": form_data.username,
            "client_ip": get_remote_address(request),
            "endpoint": "/login"
        }
    )

    user = await user_repo.get_user(form_data.username)
    if not user or not security_service.verify_password(form_data.password, user.hashed_password):
        logger.warning(
            "Failed login attempt",
            extra={
                "username": form_data.username,
                "client_ip": get_remote_address(request),
                "reason": "Invalid credentials"
            }
        )
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    settings = get_settings()
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security_service.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    logger.info(
        "Successful login",
        extra={
            "username": user.username,
            "client_ip": get_remote_address(request),
            "token_expires_in_minutes": settings.ACCESS_TOKEN_EXPIRE_MINUTES
        }
    )

    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/register", response_model=UserInDB)
@limiter.limit("20/minute")
async def register(
    request: Request,
    user: UserCreate,
    user_repo: UserRepository = Depends(get_user_repository)
):
    logger.info(
        "Registration attempt",
        extra={
            "username": user.username,
            "client_ip": get_remote_address(request),
            "endpoint": "/register"
        }
    )

    db_user = await user_repo.get_user(user.username)
    if db_user:
        logger.warning(
            "Registration failed - username taken",
            extra={
                "username": user.username,
                "client_ip": get_remote_address(request)
            }
        )
        raise HTTPException(status_code=400, detail="Username already registered")

    try:
        hashed_password = security_service.get_password_hash(user.password)
        db_user = UserInDB(**user.dict(), hashed_password=hashed_password)
        created_user = await user_repo.create_user(db_user)

        logger.info(
            "Successful registration",
            extra={
                "username": created_user.username,
                "client_ip": get_remote_address(request)
            }
        )

        return created_user

    except Exception as e:
        logger.error(
            "Registration failed - database error",
            extra={
                "username": user.username,
                "client_ip": get_remote_address(request),
                "error_type": type(e).__name__,
                "error_detail": str(e)
            }
        )
        raise HTTPException(status_code=500, detail="Error creating user")

@router.get("/verify-token")
@limiter.limit("20/minute")
async def verify_token(
    request: Request,
    current_user: UserInDB = Depends(security_service.get_current_user)
):
    logger.info(
        "Token verification attempt",
        extra={
            "username": current_user.username,
            "client_ip": get_remote_address(request),
            "endpoint": "/verify-token"
        }
    )

    try:
        logger.info(
            "Successful token verification",
            extra={
                "username": current_user.username,
                "client_ip": get_remote_address(request)
            }
        )
        return {"valid": True, "username": current_user.username}

    except Exception as e:
        logger.error(
            "Token verification failed",
            extra={
                "client_ip": get_remote_address(request),
                "error_type": type(e).__name__,
                "error_detail": str(e)
            }
        )
        raise HTTPException(status_code=401, detail="Invalid token")