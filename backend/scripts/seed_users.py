#!/usr/bin/env python3
"""
Seed default users in MongoDB (idempotent - safe to run multiple times).

Creates:
  1. Default user (role=user) for testing/demo
  2. Admin user (role=admin, is_superuser=True) for administration

Environment Variables:
  MONGODB_URL: Connection string (default: mongodb://mongo:27017/integr8scode)
  DEFAULT_USER_PASSWORD: Default user password (default: user123)
  ADMIN_USER_PASSWORD: Admin user password (default: admin123)
"""

import asyncio
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from passlib.context import CryptContext
from pydantic_settings import BaseSettings, SettingsConfigDict
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.asynchronous.mongo_client import AsyncMongoClient

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class SeedSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False)

    mongodb_url: str = "mongodb://mongo:27017/integr8scode"
    database_name: str = "integr8scode_db"
    default_user_password: str = "user123"
    admin_user_password: str = "admin123"


async def upsert_user(
    db: AsyncDatabase[dict[str, Any]],
    username: str,
    email: str,
    password: str,
    role: str,
    is_superuser: bool,
) -> None:
    """Create user or update if exists."""
    existing = await db.users.find_one({"username": username})

    if existing:
        print(f"User '{username}' exists - updating password, role={role}, is_superuser={is_superuser}")
        await db.users.update_one(
            {"username": username},
            {
                "$set": {
                    "hashed_password": pwd_context.hash(password),
                    "role": role,
                    "is_superuser": is_superuser,
                    "is_active": True,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
    else:
        print(f"Creating user '{username}' (role={role}, is_superuser={is_superuser})")
        await db.users.insert_one(
            {
                "_id": ObjectId(),
                "user_id": str(ObjectId()),
                "username": username,
                "email": email,
                "hashed_password": pwd_context.hash(password),
                "role": role,
                "is_active": True,
                "is_superuser": is_superuser,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )


async def seed_users() -> None:
    settings = SeedSettings()
    mongodb_url = settings.mongodb_url
    db_name = settings.database_name

    print(f"Connecting to MongoDB (database: {db_name})...")

    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(mongodb_url)
    db = client[db_name]

    # Default user
    await upsert_user(
        db,
        username="user",
        email="user@integr8scode.com",
        password=settings.default_user_password,
        role="user",
        is_superuser=False,
    )

    # Admin user
    await upsert_user(
        db,
        username="admin",
        email="admin@integr8scode.com",
        password=settings.admin_user_password,
        role="admin",
        is_superuser=True,
    )

    print("\n" + "=" * 50)
    print("SEEDED USERS:")
    print("=" * 50)
    print("Default: user / user123  (or DEFAULT_USER_PASSWORD)")
    print("Admin:   admin / admin123 (or ADMIN_USER_PASSWORD)")
    print("=" * 50)

    await client.close()


if __name__ == "__main__":
    asyncio.run(seed_users())
