import uuid
from typing import Any, Dict, List, Optional

from fastapi import Request
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.schemas_pydantic.user import UserInDB, UserRole


class UserRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def get_user(self, username: str) -> Optional[UserInDB]:
        user = await self.db.users.find_one({"username": username})
        if user:
            return UserInDB(**user)
        return None

    async def create_user(self, user: UserInDB) -> UserInDB:
        if not user.user_id:
            user.user_id = str(uuid.uuid4())
        user_dict = user.model_dump(exclude_unset=True)
        await self.db.users.insert_one(user_dict)
        return user

    async def get_user_by_id(self, user_id: str) -> Optional[UserInDB]:
        user = await self.db.users.find_one({"user_id": user_id})
        if user:
            return UserInDB(**user)
        return None

    async def list_users(
            self,
            limit: int = 100,
            offset: int = 0,
            search: Optional[str] = None,
            role: Optional[UserRole] = None
    ) -> List[UserInDB]:
        query: Dict[str, Any] = {}

        if search:
            query["$or"] = [
                {"username": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}}
            ]

        if role:
            query["role"] = role.value

        cursor = self.db.users.find(query).skip(offset).limit(limit)
        users = []
        async for user in cursor:
            users.append(UserInDB(**user))

        return users

    async def update_user(self, user_id: str, update_data: Dict[str, Any]) -> Optional[UserInDB]:
        # Remove None values
        update_data = {k: v for k, v in update_data.items() if v is not None}

        result = await self.db.users.update_one(
            {"user_id": user_id},
            {"$set": update_data}
        )

        if result.modified_count > 0:
            return await self.get_user_by_id(user_id)

        return None

    async def delete_user(self, user_id: str) -> bool:
        result = await self.db.users.delete_one({"user_id": user_id})
        return result.deleted_count > 0


def get_user_repository(request: Request) -> UserRepository:
    db_manager = request.app.state.db_manager
    return UserRepository(db_manager.get_database())
