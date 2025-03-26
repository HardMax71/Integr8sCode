from typing import Optional

from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.mongodb import get_database
from app.models.user import UserInDB


class UserRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def get_user(self, username: str) -> Optional[UserInDB]:
        user = await self.db.users.find_one({"username": username})
        if user:
            return UserInDB(**user)
        return None

    async def create_user(self, user: UserInDB) -> UserInDB:
        user_dict = user.dict(by_alias=True)
        await self.db.users.insert_one(user_dict)
        return user


def get_user_repository(
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> UserRepository:
    return UserRepository(db)
