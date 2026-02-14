import dataclasses
import re
from datetime import datetime, timezone

from beanie.odm.operators.find import BaseFindOperator
from beanie.operators import Eq, Or, RegEx
from pymongo.errors import DuplicateKeyError

from app.db.docs import UserDocument
from app.domain.enums import UserRole
from app.domain.exceptions import ConflictError
from app.domain.user import DomainUserCreate, DomainUserUpdate, User, UserListResult


class UserRepository:
    async def get_user(self, username: str) -> User | None:
        doc = await UserDocument.find_one(UserDocument.username == username)
        return User(**doc.model_dump(include=set(User.__dataclass_fields__))) if doc else None

    async def create_user(self, create_data: DomainUserCreate) -> User:
        doc = UserDocument(**dataclasses.asdict(create_data))
        try:
            await doc.insert()
        except DuplicateKeyError as e:
            raise ConflictError("User already exists") from e
        return User(**doc.model_dump(include=set(User.__dataclass_fields__)))

    async def get_user_by_id(self, user_id: str) -> User | None:
        doc = await UserDocument.find_one(UserDocument.user_id == user_id)
        return User(**doc.model_dump(include=set(User.__dataclass_fields__))) if doc else None

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
            users=[User(**d.model_dump(include=set(User.__dataclass_fields__))) for d in docs],
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
        return User(**doc.model_dump(include=set(User.__dataclass_fields__)))

    async def delete_user(self, user_id: str) -> bool:
        doc = await UserDocument.find_one(UserDocument.user_id == user_id)
        if not doc:
            return False
        await doc.delete()
        return True
