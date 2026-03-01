import dataclasses
import re
from datetime import datetime, timezone

from beanie.odm.operators.find import BaseFindOperator
from beanie.operators import Eq, Or, RegEx
from pymongo.errors import DuplicateKeyError

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
from app.domain.exceptions import ConflictError
from app.domain.user import (
    DomainUserCreate,
    DomainUserUpdate,
    PasswordReset,
    User,
    UserDeleteResult,
    UserListResult,
    UserNotFoundError,
)

_user_fields = set(User.__dataclass_fields__)


class UserRepository:
    async def get_user(self, username: str) -> User | None:
        doc = await UserDocument.find_one(UserDocument.username == username)
        return User(**doc.model_dump(include=_user_fields)) if doc else None

    async def create_user(self, create_data: DomainUserCreate) -> User:
        doc = UserDocument(**dataclasses.asdict(create_data))
        try:
            await doc.insert()
        except DuplicateKeyError as e:
            raise ConflictError("User already exists") from e
        return User(**doc.model_dump(include=_user_fields))

    async def get_user_by_email(self, email: str) -> User | None:
        doc = await UserDocument.find_one(UserDocument.email == email)
        return User(**doc.model_dump(include=_user_fields)) if doc else None

    async def get_user_by_id(self, user_id: str) -> User | None:
        doc = await UserDocument.find_one(UserDocument.user_id == user_id)
        return User(**doc.model_dump(include=_user_fields)) if doc else None

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
        return UserListResult(
            users=[User(**d.model_dump(include=_user_fields)) for d in docs],
            total=total,
            offset=offset,
            limit=limit,
        )

    async def update_user(self, user_id: str, update_data: DomainUserUpdate) -> User | None:
        doc = await UserDocument.find_one(UserDocument.user_id == user_id)
        if not doc:
            return None

        update_dict = {k: v for k, v in dataclasses.asdict(update_data).items() if v is not None}
        if update_dict:
            update_dict["updated_at"] = datetime.now(timezone.utc)
            await doc.set(update_dict)
        return User(**doc.model_dump(include=_user_fields))

    async def delete_user(self, user_id: str, cascade: bool = False) -> UserDeleteResult:
        doc = await UserDocument.find_one(UserDocument.user_id == user_id)
        if not doc:
            raise UserNotFoundError(user_id)

        await doc.delete()

        if not cascade:
            return UserDeleteResult(user_deleted=True)

        exec_result = await ExecutionDocument.find(ExecutionDocument.user_id == user_id).delete()
        scripts_result = await SavedScriptDocument.find(SavedScriptDocument.user_id == user_id).delete()
        notif_result = await NotificationDocument.find(NotificationDocument.user_id == user_id).delete()
        settings_result = await UserSettingsDocument.find(UserSettingsDocument.user_id == user_id).delete()
        events_result = await EventDocument.find(EventDocument.metadata.user_id == user_id).delete()
        sagas_result = await SagaDocument.find(SagaDocument.context_data.user_id == user_id).delete()

        return UserDeleteResult(
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
