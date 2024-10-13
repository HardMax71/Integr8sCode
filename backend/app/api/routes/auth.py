from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta
from app.core.security import security_service
from app.config import get_settings
from app.db.repositories.user_repository import UserRepository, get_user_repository
from app.models.user import UserCreate, UserInDB
from slowapi import Limiter
from slowapi.util import get_remote_address

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

@router.post("/login")
@limiter.limit("20/minute")
async def login(request: Request,
                form_data: OAuth2PasswordRequestForm = Depends(), user_repo: UserRepository = Depends(get_user_repository)):
    user = await user_repo.get_user(form_data.username)
    if not user or not security_service.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    settings = get_settings()
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security_service.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/register", response_model=UserInDB)
@limiter.limit("20/minute")
async def register(request: Request,
                   user: UserCreate, user_repo: UserRepository = Depends(get_user_repository)):
    db_user = await user_repo.get_user(user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_password = security_service.get_password_hash(user.password)
    db_user = UserInDB(**user.dict(), hashed_password=hashed_password)
    return await user_repo.create_user(db_user)

@router.get("/verify-token")
@limiter.limit("20/minute")
async def verify_token(request: Request,
                       current_user: UserInDB = Depends(security_service.get_current_user)):
    return {"valid": True, "username": current_user.username}