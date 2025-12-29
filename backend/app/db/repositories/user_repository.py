import re
from dataclasses import asdict
from datetime import datetime, timezone

from beanie.odm.operators.find import BaseFindOperator
from beanie.operators import Eq, Or, RegEx

from app.db.docs import UserDocument
from app.domain.enums.user import UserRole
from app.domain.user import DomainUserCreate, DomainUserUpdate


class UserRepository:

    async def get_user(self, username: str) -> UserDocument | None:
        return await UserDocument.find_one({"username": username})

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

    async def get_user_by_id(self, user_id: str) -> UserDocument | None:
        return await UserDocument.find_one({"user_id": user_id})

    async def list_users(
        self, limit: int = 100, offset: int = 0, search: str | None = None, role: UserRole | None = None
    ) -> list[UserDocument]:
        conditions: list[BaseFindOperator] = []

        if search:
            escaped_search = re.escape(search)
            conditions.append(Or(
                RegEx(UserDocument.username, escaped_search, options="i"),
                RegEx(UserDocument.email, escaped_search, options="i"),
            ))

        if role:
            conditions.append(Eq(UserDocument.role, role))

        return await UserDocument.find(*conditions).skip(offset).limit(limit).to_list()

    async def update_user(self, user_id: str, update_data: DomainUserUpdate) -> UserDocument | None:
        doc = await self.get_user_by_id(user_id)
        if not doc:
            return None

        update_dict = {k: v for k, v in asdict(update_data).items() if v is not None}
        if update_dict:
            update_dict["updated_at"] = datetime.now(timezone.utc)
            await doc.set(update_dict)
        return doc

    async def delete_user(self, user_id: str) -> bool:
        doc = await self.get_user_by_id(user_id)
        if not doc:
            return False
        await doc.delete()
        return True
