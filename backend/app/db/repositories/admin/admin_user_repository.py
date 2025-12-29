import re
from dataclasses import asdict
from datetime import datetime, timezone

from beanie.odm.operators.find import BaseFindOperator
from beanie.operators import Eq, Or, RegEx

from app.core.security import SecurityService
from app.db.docs import (
    EventDocument,
    ExecutionDocument,
    NotificationDocument,
    SagaDocument,
    SavedScriptDocument,
    UserDocument,
    UserSettingsDocument,
)
from app.domain.enums import UserRole
from app.domain.user import DomainUserCreate, PasswordReset, User, UserListResult, UserUpdate


class AdminUserRepository:
    def __init__(self) -> None:
        self.security_service = SecurityService()

    async def create_user(self, create_data: DomainUserCreate) -> UserDocument:
        doc = UserDocument(
            username=create_data.username,
            email=create_data.email,
            hashed_password=create_data.hashed_password,
            role=create_data.role,
            is_active=create_data.is_active,
            is_superuser=create_data.is_superuser,
        )
        await doc.insert()
        return doc

    async def list_users(
        self, limit: int = 100, offset: int = 0, search: str | None = None, role: UserRole | None = None
    ) -> UserListResult:
        conditions: list[BaseFindOperator] = []

        if search:
            escaped_search = re.escape(search)
            conditions.append(
                Or(
                    RegEx(UserDocument.username, escaped_search, options="i"),
                    RegEx(UserDocument.email, escaped_search, options="i"),
                )
            )

        if role:
            conditions.append(Eq(UserDocument.role, role))

        query = UserDocument.find(*conditions)
        total = await query.count()
        docs = await query.skip(offset).limit(limit).to_list()
        users = [User(**doc.model_dump(exclude={"id"})) for doc in docs]
        return UserListResult(users=users, total=total, offset=offset, limit=limit)

    async def get_user_by_id(self, user_id: str) -> UserDocument | None:
        return await UserDocument.find_one({"user_id": user_id})

    async def update_user(self, user_id: str, update_data: UserUpdate) -> UserDocument | None:
        doc = await self.get_user_by_id(user_id)
        if not doc:
            return None

        update_dict = {k: v for k, v in asdict(update_data).items() if v is not None}
        # Handle password hashing
        if "password" in update_dict:
            update_dict["hashed_password"] = self.security_service.get_password_hash(update_dict.pop("password"))

        if update_dict:
            update_dict["updated_at"] = datetime.now(timezone.utc)
            await doc.set(update_dict)
        return doc

    async def delete_user(self, user_id: str, cascade: bool = True) -> dict[str, int]:
        deleted_counts = {}

        doc = await self.get_user_by_id(user_id)
        if doc:
            await doc.delete()
            deleted_counts["user"] = 1
        else:
            deleted_counts["user"] = 0

        if not cascade:
            return deleted_counts

        # Cascade delete related data
        exec_result = await ExecutionDocument.find({"user_id": user_id}).delete()
        deleted_counts["executions"] = exec_result.deleted_count if exec_result else 0

        scripts_result = await SavedScriptDocument.find({"user_id": user_id}).delete()
        deleted_counts["saved_scripts"] = scripts_result.deleted_count if scripts_result else 0

        notif_result = await NotificationDocument.find({"user_id": user_id}).delete()
        deleted_counts["notifications"] = notif_result.deleted_count if notif_result else 0

        settings_result = await UserSettingsDocument.find({"user_id": user_id}).delete()
        deleted_counts["user_settings"] = settings_result.deleted_count if settings_result else 0

        events_result = await EventDocument.find({"metadata.user_id": user_id}).delete()
        deleted_counts["events"] = events_result.deleted_count if events_result else 0

        sagas_result = await SagaDocument.find({"context_data.user_id": user_id}).delete()
        deleted_counts["sagas"] = sagas_result.deleted_count if sagas_result else 0

        return deleted_counts

    async def reset_user_password(self, reset_data: PasswordReset) -> bool:
        doc = await self.get_user_by_id(reset_data.user_id)
        if not doc:
            return False

        doc.hashed_password = self.security_service.get_password_hash(reset_data.new_password)
        doc.updated_at = datetime.now(timezone.utc)
        await doc.save()
        return True
