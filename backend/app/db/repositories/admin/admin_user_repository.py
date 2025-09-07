from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.logging import logger
from app.core.security import SecurityService
from app.domain.admin.user_models import (
    PasswordReset,
    User,
    UserFields,
    UserListResult,
    UserSearchFilter,
    UserUpdate,
)
from app.infrastructure.mappers.admin_mapper import UserMapper


class AdminUserRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.users_collection: AsyncIOMotorCollection = self.db.get_collection("users")
        self.security_service = SecurityService()
        self.mapper = UserMapper()

    async def list_users(
            self,
            limit: int = 100,
            offset: int = 0,
            search: str | None = None,
            role: str | None = None
    ) -> UserListResult:
        """List all users with optional filtering."""
        try:
            # Create search filter
            from app.domain.enums.user import UserRole
            search_filter = UserSearchFilter(
                search_text=search,
                role=UserRole(role) if role else None
            )

            query = search_filter.to_query()

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

        except Exception as e:
            logger.error(f"Error listing users: {e}")
            raise

    async def get_user_by_id(self, user_id: str) -> User | None:
        """Get user by ID."""
        try:
            user_doc = await self.users_collection.find_one({UserFields.USER_ID: user_id})
            if user_doc:
                return self.mapper.from_mongo_document(user_doc)
            return None

        except Exception as e:
            logger.error(f"Error getting user by ID: {e}")
            raise

    async def update_user(
            self,
            user_id: str,
            update_data: UserUpdate
    ) -> User | None:
        """Update user details."""
        try:
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

        except Exception as e:
            logger.error(f"Error updating user: {e}")
            raise

    async def delete_user(self, user_id: str, cascade: bool = True) -> dict[str, int]:
        """Delete user with optional cascade deletion of related data."""
        try:
            deleted_counts = {}
            
            if cascade:
                # Delete user's executions
                executions_result = await self.db.get_collection("executions").delete_many(
                    {"user_id": user_id}
                )
                deleted_counts["executions"] = executions_result.deleted_count
                
                # Delete user's saved scripts
                scripts_result = await self.db.get_collection("saved_scripts").delete_many(
                    {"user_id": user_id}
                )
                deleted_counts["saved_scripts"] = scripts_result.deleted_count
                
                # Delete user's notifications
                notifications_result = await self.db.get_collection("notifications").delete_many(
                    {"user_id": user_id}
                )
                deleted_counts["notifications"] = notifications_result.deleted_count
                
                # Delete user's settings
                settings_result = await self.db.get_collection("user_settings").delete_many(
                    {"user_id": user_id}
                )
                deleted_counts["user_settings"] = settings_result.deleted_count
                
                # Delete user's events (if needed)
                events_result = await self.db.get_collection("events").delete_many(
                    {"metadata.user_id": user_id}
                )
                deleted_counts["events"] = events_result.deleted_count
                
                # Delete user's sagas
                sagas_result = await self.db.get_collection("sagas").delete_many(
                    {"user_id": user_id}
                )
                deleted_counts["sagas"] = sagas_result.deleted_count
            
            # Delete the user
            result = await self.users_collection.delete_one({UserFields.USER_ID: user_id})
            deleted_counts["user"] = result.deleted_count
            
            return deleted_counts

        except Exception as e:
            logger.error(f"Error deleting user: {e}")
            raise

    async def reset_user_password(self, password_reset: PasswordReset) -> bool:
        """Reset user password."""
        try:
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

        except Exception as e:
            logger.error(f"Error resetting user password: {e}")
            raise
