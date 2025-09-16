from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.security import SecurityService
from app.domain.enums import UserRole
from app.domain.events.event_models import CollectionNames
from app.domain.user import (
    PasswordReset,
    User,
    UserFields,
    UserListResult,
    UserSearchFilter,
    UserUpdate,
)
from app.infrastructure.mappers import UserMapper


class AdminUserRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.users_collection: AsyncIOMotorCollection = self.db.get_collection(CollectionNames.USERS)

        # Related collections used by this repository (e.g., cascade deletes)
        self.executions_collection: AsyncIOMotorCollection = self.db.get_collection(CollectionNames.EXECUTIONS)
        self.saved_scripts_collection: AsyncIOMotorCollection = self.db.get_collection(CollectionNames.SAVED_SCRIPTS)
        self.notifications_collection: AsyncIOMotorCollection = self.db.get_collection(CollectionNames.NOTIFICATIONS)
        self.user_settings_collection: AsyncIOMotorCollection = self.db.get_collection(CollectionNames.USER_SETTINGS)
        self.events_collection: AsyncIOMotorCollection = self.db.get_collection(CollectionNames.EVENTS)
        self.sagas_collection: AsyncIOMotorCollection = self.db.get_collection(CollectionNames.SAGAS)
        self.security_service = SecurityService()
        self.mapper = UserMapper()

    async def list_users(
            self,
            limit: int = 100,
            offset: int = 0,
            search: str | None = None,
            role: UserRole | None = None
    ) -> UserListResult:
        """List all users with optional filtering."""
        # Create search filter
        search_filter = UserSearchFilter(
            search_text=search,
            role=role
        )

        query = self.mapper.search_filter_to_query(search_filter)

        # Get total count
        total = await self.users_collection.count_documents(query)

        # Get users with pagination
        cursor = self.users_collection.find(query).skip(offset).limit(limit)

        users = []
        async for user_doc in cursor:
            users.append(self.mapper.from_mongo_document(user_doc))

        return UserListResult(
            users=users,
            total=total,
            offset=offset,
            limit=limit
        )

    async def get_user_by_id(self, user_id: str) -> User | None:
        """Get user by ID."""
        user_doc = await self.users_collection.find_one({UserFields.USER_ID: user_id})
        if user_doc:
            return self.mapper.from_mongo_document(user_doc)
        return None

    async def update_user(
            self,
            user_id: str,
            update_data: UserUpdate
    ) -> User | None:
        """Update user details."""
        if not update_data.has_updates():
            return await self.get_user_by_id(user_id)

        # Get update dict
        update_dict = self.mapper.to_update_dict(update_data)

        # Hash password if provided
        if update_data.password:
            update_dict[UserFields.HASHED_PASSWORD] = self.security_service.get_password_hash(update_data.password)
            # Ensure no plaintext password field is persisted
            update_dict.pop("password", None)

        # Add updated_at timestamp
        update_dict[UserFields.UPDATED_AT] = datetime.now(timezone.utc)

        result = await self.users_collection.update_one(
            {UserFields.USER_ID: user_id},
            {"$set": update_dict}
        )

        if result.modified_count > 0:
            return await self.get_user_by_id(user_id)

        return None

    async def delete_user(self, user_id: str, cascade: bool = True) -> dict[str, int]:
        """Delete user with optional cascade deletion of related data."""
        deleted_counts = {}

        result = await self.users_collection.delete_one({UserFields.USER_ID: user_id})
        deleted_counts["user"] = result.deleted_count

        if not cascade:
            return deleted_counts

        # Delete user's executions
        executions_result = await self.executions_collection.delete_many({"user_id": user_id})
        deleted_counts["executions"] = executions_result.deleted_count

        # Delete user's saved scripts
        scripts_result = await self.saved_scripts_collection.delete_many({"user_id": user_id})
        deleted_counts["saved_scripts"] = scripts_result.deleted_count

        # Delete user's notifications
        notifications_result = await self.notifications_collection.delete_many({"user_id": user_id})
        deleted_counts["notifications"] = notifications_result.deleted_count

        # Delete user's settings
        settings_result = await self.user_settings_collection.delete_many({"user_id": user_id})
        deleted_counts["user_settings"] = settings_result.deleted_count

        # Delete user's events (if needed)
        events_result = await self.events_collection.delete_many({"user_id": user_id})
        deleted_counts["events"] = events_result.deleted_count

        # Delete user's sagas
        sagas_result = await self.sagas_collection.delete_many({"user_id": user_id})
        deleted_counts["sagas"] = sagas_result.deleted_count

        return deleted_counts

    async def reset_user_password(self, password_reset: PasswordReset) -> bool:
        """Reset user password."""
        if not password_reset.is_valid():
            raise ValueError("Invalid password reset data")

        hashed_password = self.security_service.get_password_hash(password_reset.new_password)

        result = await self.users_collection.update_one(
            {UserFields.USER_ID: password_reset.user_id},
            {"$set": {
                UserFields.HASHED_PASSWORD: hashed_password,
                UserFields.UPDATED_AT: datetime.now(timezone.utc)
            }}
        )

        return result.modified_count > 0
