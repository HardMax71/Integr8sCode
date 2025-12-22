import re
import uuid
from datetime import datetime, timezone

from app.core.database_context import Collection, Database
from app.domain.enums.user import UserRole
from app.domain.events.event_models import CollectionNames
from app.domain.user import User as DomainAdminUser
from app.domain.user import UserFields
from app.domain.user import UserUpdate as DomainUserUpdate
from app.infrastructure.mappers import UserMapper


class UserRepository:
    def __init__(self, db: Database):
        self.db = db
        self.collection: Collection = self.db.get_collection(CollectionNames.USERS)
        self.mapper = UserMapper()

    async def get_user(self, username: str) -> DomainAdminUser | None:
        user = await self.collection.find_one({UserFields.USERNAME: username})
        if user:
            return self.mapper.from_mongo_document(user)
        return None

    async def create_user(self, user: DomainAdminUser) -> DomainAdminUser:
        if not user.user_id:
            user.user_id = str(uuid.uuid4())
        # Ensure timestamps
        if not getattr(user, "created_at", None):
            user.created_at = datetime.now(timezone.utc)
        if not getattr(user, "updated_at", None):
            user.updated_at = user.created_at
        user_dict = self.mapper.to_mongo_document(user)
        await self.collection.insert_one(user_dict)
        return user

    async def get_user_by_id(self, user_id: str) -> DomainAdminUser | None:
        user = await self.collection.find_one({UserFields.USER_ID: user_id})
        if user:
            return self.mapper.from_mongo_document(user)
        return None

    async def list_users(
            self,
            limit: int = 100,
            offset: int = 0,
            search: str | None = None,
            role: UserRole | None = None
    ) -> list[DomainAdminUser]:
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

        cursor = self.collection.find(query).skip(offset).limit(limit)
        users: list[DomainAdminUser] = []
        async for user in cursor:
            users.append(self.mapper.from_mongo_document(user))

        return users

    async def update_user(self, user_id: str, update_data: DomainUserUpdate) -> DomainAdminUser | None:
        update_dict = self.mapper.to_update_dict(update_data)
        if not update_dict and update_data.password is None:
            return await self.get_user_by_id(user_id)
        # Handle password update separately if provided
        if update_data.password:
            update_dict[UserFields.HASHED_PASSWORD] = update_data.password  # caller should pass hashed if desired
        update_dict[UserFields.UPDATED_AT] = datetime.now(timezone.utc)
        result = await self.collection.update_one(
            {UserFields.USER_ID: user_id},
            {"$set": update_dict}
        )
        if result.modified_count > 0:
            return await self.get_user_by_id(user_id)
        return None

    async def delete_user(self, user_id: str) -> bool:
        result = await self.collection.delete_one({UserFields.USER_ID: user_id})
        return result.deleted_count > 0
