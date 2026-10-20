import re
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog
from beanie.odm.operators.find import BaseFindOperator
from beanie.operators import Eq, In, NotIn, Or, RegEx
from pydantic import SecretStr
from pymongo.errors import DuplicateKeyError

from app.db.docs import (
    EventDocument,
    ExecutionDocument,
    NotificationDocument,
    SavedScriptDocument,
    UserDocument,
    UserSettingsDocument,
)
from app.domain.enums import UserRole
from app.domain.exceptions import ConflictError
from app.domain.user import UserChanges, UserDeleteResult


@dataclass
class UserListResult:
    users: list[UserDocument]
    total: int
    offset: int
    limit: int


class UserRepository:
    def __init__(self, logger: structlog.stdlib.BoundLogger) -> None:
        self.logger = logger

    async def get_user(self, username: str) -> UserDocument | None:
        return await UserDocument.find_one(UserDocument.username == username)

    async def create_user(self, user: UserDocument) -> None:
        try:
            await user.insert()
        except DuplicateKeyError as e:
            raise ConflictError("User already exists") from e

    async def get_user_by_email(self, email: str) -> UserDocument | None:
        return await UserDocument.find_one(UserDocument.email == email)

    async def get_user_by_id(self, user_id: str) -> UserDocument | None:
        return await UserDocument.find_one(UserDocument.user_id == user_id)

    async def list_users(
        self,
        limit: int = 100,
        offset: int = 0,
        search: str | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
        user_ids: set[str] | None = None,
        excluded_user_ids: set[str] | None = None,
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

        if is_active is not None:
            conditions.append(Eq(UserDocument.is_active, is_active))

        if user_ids is not None:
            conditions.append(In(UserDocument.user_id, list(user_ids)))

        if excluded_user_ids:
            conditions.append(NotIn(UserDocument.user_id, list(excluded_user_ids)))

        query = UserDocument.find(*conditions)
        total = await query.count()
        return UserListResult(
            users=await query.skip(offset).limit(limit).to_list(),
            total=total,
            offset=offset,
            limit=limit,
        )

    async def update_user(self, user_id: str, changes: UserChanges) -> UserDocument | None:
        doc = await UserDocument.find_one(UserDocument.user_id == user_id)
        if not doc:
            return None
        try:
            await doc.set({**changes, "updated_at": datetime.now(timezone.utc)})
        except DuplicateKeyError as e:
            field = next(iter((e.details or {}).get("keyPattern", {})), "username or email")
            raise ConflictError(f"{field.capitalize()} already exists") from e
        return doc

    async def delete_user(self, user_id: str, cascade: bool = False) -> UserDeleteResult | None:
        doc = await UserDocument.find_one(UserDocument.user_id == user_id)
        if not doc:
            return None

        await doc.delete()

        if not cascade:
            return UserDeleteResult(user_deleted=True)

        exec_result = await ExecutionDocument.find(ExecutionDocument.user_id == user_id).delete()
        scripts_result = await SavedScriptDocument.find(SavedScriptDocument.user_id == user_id).delete()
        notif_result = await NotificationDocument.find(NotificationDocument.user_id == user_id).delete()
        settings_result = await UserSettingsDocument.find(UserSettingsDocument.user_id == user_id).delete()
        events_result = await EventDocument.find(EventDocument.metadata.user_id == user_id).delete()

        return UserDeleteResult(
            user_deleted=True,
            executions=exec_result.deleted_count if exec_result else 0,
            saved_scripts=scripts_result.deleted_count if scripts_result else 0,
            notifications=notif_result.deleted_count if notif_result else 0,
            user_settings=settings_result.deleted_count if settings_result else 0,
            events=events_result.deleted_count if events_result else 0,
        )

    async def reset_user_password(self, user_id: str, hashed_password: SecretStr) -> bool:
        doc = await UserDocument.find_one(UserDocument.user_id == user_id)
        if not doc:
            return False
        await doc.set({"hashed_password": hashed_password, "updated_at": datetime.now(timezone.utc)})
        return True
