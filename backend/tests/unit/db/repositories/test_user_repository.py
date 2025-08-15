import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest
from app.core.security import security_service
from app.core.service_dependencies import get_user_repository
from app.db.repositories.user_repository import (
    UserRepository
)
from app.schemas_pydantic.user import UserInDB
from motor.motor_asyncio import AsyncIOMotorDatabase


class TestUserRepository:

    @pytest.fixture(autouse=True)
    async def setup(self, db: AsyncGenerator) -> None:
        self.db = db
        self.repo = get_user_repository(db)
        self.security_service = security_service

    def test_user_repository_init(self, db: AsyncGenerator) -> None:
        repo = UserRepository(db)

        assert repo.db == db
        assert isinstance(repo.db, AsyncIOMotorDatabase)

    @pytest.mark.asyncio
    async def test_get_user_not_found(self) -> None:
        repo = get_user_repository(self.db)

        result = await repo.get_user("nonexistent_user_12345")

        assert result is None

    @pytest.mark.asyncio
    async def test_create_and_get_user_success(self) -> None:
        repo = get_user_repository(self.db)

        # Create unique username for test
        username = f"testuser_{int(asyncio.get_event_loop().time())}"
        hashed_pass = self.security_service.get_password_hash(username)

        user = UserInDB(
            id="507f1f77bcf86cd799439011",
            username=username,
            email="test@example.com",
            hashed_password=hashed_pass,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        # Create user in database
        created_user = await repo.create_user(user)

        assert created_user is not None
        assert created_user.username == username
        assert created_user.email == user.email
        assert created_user.hashed_password == hashed_pass

        # Retrieve the user
        retrieved_user = await repo.get_user(username)

        assert retrieved_user is not None
        assert isinstance(retrieved_user, UserInDB)
        assert retrieved_user.username == username
        assert retrieved_user.email == "test@example.com"
        assert retrieved_user.hashed_password == hashed_pass

    @pytest.mark.asyncio
    async def test_get_user_empty_username(self) -> None:
        repo = get_user_repository(self.db)

        result = await repo.get_user("")

        assert result is None

    @pytest.mark.asyncio
    async def test_create_user_returns_same_instance(self) -> None:
        repo = get_user_repository(self.db)

        username = f"sameuser_{int(asyncio.get_event_loop().time())}"

        user = UserInDB(
            id="507f1f77bcf86cd799439011",
            username=username,
            email="same@example.com",
            hashed_password=self.security_service.get_password_hash("testpass"),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        result = await repo.create_user(user)

        # Should return the exact same instance
        assert result is user

    @pytest.mark.asyncio
    async def test_create_multiple_users(self) -> None:
        repo = get_user_repository(self.db)

        timestamp = int(asyncio.get_event_loop().time())
        users = []

        for i in range(3):
            user = UserInDB(
                id=f"507f1f77bcf86cd79943901{i}",
                username=f"multiuser_{i}_{timestamp}",
                email=f"multi{i}@example.com",
                hashed_password=self.security_service.get_password_hash("testpass"),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )

            created_user = await repo.create_user(user)
            users.append(created_user)

            assert created_user.username == f"multiuser_{i}_{timestamp}"
            assert created_user.email == f"multi{i}@example.com"

        # Verify all users can be retrieved
        for user in users:
            retrieved = await repo.get_user(user.username)
            assert retrieved is not None
            assert retrieved.username == user.username

    @pytest.mark.asyncio
    async def test_user_password_hashing_integration(self) -> None:
        repo = get_user_repository(self.db)

        username = f"hashuser_{int(asyncio.get_event_loop().time())}"
        plain_password = "secure_password_123"

        user = UserInDB(
            id="507f1f77bcf86cd799439011",
            username=username,
            email="hash@example.com",
            hashed_password=self.security_service.get_password_hash(plain_password),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        await repo.create_user(user)
        retrieved_user = await repo.get_user(username)

        assert retrieved_user is not None
        # Verify password hash is not the plain password
        assert retrieved_user.hashed_password != plain_password
        # Verify password can be verified
        assert self.security_service.verify_password(plain_password, retrieved_user.hashed_password)
        assert not self.security_service.verify_password("wrong_password", retrieved_user.hashed_password)


class TestGetUserRepository:

    def test_get_user_repository_returns_repository(self, db: AsyncGenerator) -> None:
        result = get_user_repository(db)

        assert isinstance(result, UserRepository)
        assert result.db == db
        assert isinstance(result.db, AsyncIOMotorDatabase)

    def test_get_user_repository_with_none_db(self) -> None:
        result = get_user_repository(None)

        assert isinstance(result, UserRepository)
        assert result.db is None

    def test_get_user_repository_integration(self, db: AsyncGenerator) -> None:

        # Test dependency injection pattern
        result = get_user_repository(db)

        assert isinstance(result, UserRepository)
        assert result.db == db

        # Test that repository is functional
        assert hasattr(result, 'get_user')
        assert hasattr(result, 'create_user')
        assert callable(result.get_user)
        assert callable(result.create_user)
