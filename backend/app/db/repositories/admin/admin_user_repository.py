from datetime import datetime, timezone
from typing import Optional

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


class AdminUserRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.users_collection: AsyncIOMotorCollection = self.db.get_collection("users")
        self.security_service = SecurityService()

    async def list_users(
            self,
            limit: int = 100,
            offset: int = 0,
            search: Optional[str] = None,
            role: Optional[str] = None
    ) -> UserListResult:
        """List all users with optional filtering."""
        try:
            # Create search filter
            from app.domain.admin.user_models import UserRole
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
                users.append(User.from_dict(user_doc))

            return UserListResult(
                users=users,
                total=total,
                offset=offset,
                limit=limit
            )

        except Exception as e:
            logger.error(f"Error listing users: {e}")
            raise

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        try:
            user_doc = await self.users_collection.find_one({UserFields.USER_ID: user_id})
            if user_doc:
                return User.from_dict(user_doc)
            return None

        except Exception as e:
            logger.error(f"Error getting user by ID: {e}")
            raise

    async def update_user(
            self,
            user_id: str,
            update_data: UserUpdate
    ) -> Optional[User]:
        """Update user details."""
        try:
            if not update_data.has_updates():
                return await self.get_user_by_id(user_id)

            # Get update dict
            update_dict = update_data.to_update_dict()

            # Hash password if provided
            if update_data.password:
                update_dict[UserFields.HASHED_PASSWORD] = self.security_service.get_password_hash(update_data.password)

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

    async def delete_user(self, user_id: str) -> bool:
        """Delete user."""
        try:
            result = await self.users_collection.delete_one({UserFields.USER_ID: user_id})
            return result.deleted_count > 0

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
