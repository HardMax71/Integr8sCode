import re
import uuid

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.schemas_pydantic.user import UserInDB, UserRole


class UserRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def get_user(self, username: str) -> UserInDB | None:
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

    async def get_user_by_id(self, user_id: str) -> UserInDB | None:
        user = await self.db.users.find_one({"user_id": user_id})
        if user:
            return UserInDB(**user)
        return None

    async def list_users(
            self,
            limit: int = 100,
            offset: int = 0,
            search: str | None = None,
            role: UserRole | None = None
    ) -> list[UserInDB]:
        query: dict[str, object] = {}

        if search:
            # Escape special regex characters to prevent ReDoS attacks
            escaped_search = re.escape(search)
            query["$or"] = [
                {"username": {"$regex": escaped_search, "$options": "i"}},
                {"email": {"$regex": escaped_search, "$options": "i"}}
            ]

        if role:
            query["role"] = role.value

        cursor = self.db.users.find(query).skip(offset).limit(limit)
        users = []
        async for user in cursor:
            users.append(UserInDB(**user))

        return users

    async def update_user(self, user_id: str, update_data: UserInDB) -> UserInDB | None:
        result = await self.db.users.update_one(
            {"user_id": user_id},
            {"$set": update_data.model_dump()}
        )

        if result.modified_count > 0:
            return await self.get_user_by_id(user_id)

        return None

    async def delete_user(self, user_id: str) -> bool:
        result = await self.db.users.delete_one({"user_id": user_id})
        return result.deleted_count > 0
