from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.models.user import UserInDB
from app.db.mongodb import get_database
from app.config import get_settings

class UserRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def get_user(self, username: str) -> UserInDB:
        user = await self.db.users.find_one({"username": username})
        if user:
            return UserInDB(**user)
        return None

    async def create_user(self, user: UserInDB):
        user_dict = user.dict()
        await self.db.users.insert_one(user_dict)
        return user

def get_user_repository(db: AsyncIOMotorDatabase = Depends(get_database)) -> UserRepository:
    return UserRepository(db)