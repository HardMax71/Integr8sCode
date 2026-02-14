import re
from datetime import datetime, timezone

from beanie.odm.operators.find import BaseFindOperator
from beanie.operators import Eq, Or, RegEx

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
from app.domain.user import (
    DomainUserCreate,
    PasswordReset,
    User,
    UserListResult,
    UserNotFoundError,
    UserUpdate,
)
from app.schemas_pydantic.user import DeleteUserResponse


class AdminUserRepository:

    async def create_user(self, create_data: DomainUserCreate) -> User:
        doc = UserDocument(**create_data.model_dump())
        await doc.insert()
        return User.model_validate(doc)

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
        users = [User.model_validate(doc) for doc in docs]
        return UserListResult(users=users, total=total, offset=offset, limit=limit)

    async def get_user_by_id(self, user_id: str) -> User | None:
        doc = await UserDocument.find_one(UserDocument.user_id == user_id)
        return User.model_validate(doc) if doc else None

    async def update_user(self, user_id: str, update_data: UserUpdate) -> User | None:
        doc = await UserDocument.find_one(UserDocument.user_id == user_id)
        if not doc:
            return None

        update_dict = update_data.model_dump(exclude_none=True)
        if "password" in update_dict:
            update_dict["hashed_password"] = update_dict.pop("password")

        if update_dict:
            update_dict["updated_at"] = datetime.now(timezone.utc)
            await doc.set(update_dict)
        return User.model_validate(doc)

    async def delete_user(self, user_id: str, cascade: bool = True) -> DeleteUserResponse:
        doc = await UserDocument.find_one(UserDocument.user_id == user_id)
        if not doc:
            raise UserNotFoundError(user_id)

        await doc.delete()

        if not cascade:
            return DeleteUserResponse(user_deleted=True)

        # Cascade delete related data
        exec_result = await ExecutionDocument.find(ExecutionDocument.user_id == user_id).delete()
        scripts_result = await SavedScriptDocument.find(SavedScriptDocument.user_id == user_id).delete()
        notif_result = await NotificationDocument.find(NotificationDocument.user_id == user_id).delete()
        settings_result = await UserSettingsDocument.find(UserSettingsDocument.user_id == user_id).delete()
        events_result = await EventDocument.find(EventDocument.metadata.user_id == user_id).delete()
        sagas_result = await SagaDocument.find(SagaDocument.context_data.user_id == user_id).delete()

        return DeleteUserResponse(
            user_deleted=True,
            executions=exec_result.deleted_count if exec_result else 0,
            saved_scripts=scripts_result.deleted_count if scripts_result else 0,
            notifications=notif_result.deleted_count if notif_result else 0,
            user_settings=settings_result.deleted_count if settings_result else 0,
            events=events_result.deleted_count if events_result else 0,
            sagas=sagas_result.deleted_count if sagas_result else 0,
        )

    async def reset_user_password(self, reset_data: PasswordReset) -> bool:
        doc = await UserDocument.find_one(UserDocument.user_id == reset_data.user_id)
        if not doc:
            return False

        doc.hashed_password = reset_data.new_password
        doc.updated_at = datetime.now(timezone.utc)
        await doc.save()
        return True
