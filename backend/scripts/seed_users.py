#!/usr/bin/env python3
"""
Seed default users in MongoDB (idempotent - safe to run multiple times).

Creates:
  1. Default user (role=user) for testing/demo
  2. Admin user (role=admin, is_superuser=True) for administration

Uses main Settings for MongoDB connection. Password env vars are script-specific:
  DEFAULT_USER_PASSWORD: Default user password (default: user123)
  ADMIN_USER_PASSWORD: Admin user password (default: admin123)
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

from app.settings import Settings
from bson import ObjectId
from passlib.context import CryptContext
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.asynchronous.mongo_client import AsyncMongoClient

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


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


async def seed_users(settings: Settings) -> None:
    """Seed default users using provided settings for MongoDB connection."""
    default_password = os.environ.get("DEFAULT_USER_PASSWORD", "user123")
    admin_password = os.environ.get("ADMIN_USER_PASSWORD", "admin123")

    print(f"Connecting to MongoDB (database: {settings.DATABASE_NAME})...")

    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.MONGODB_URL)
    db = client[settings.DATABASE_NAME]

    # Default user
    await upsert_user(
        db,
        username="user",
        email="user@integr8scode.com",
        password=default_password,
        role="user",
        is_superuser=False,
    )

    # Admin user
    await upsert_user(
        db,
        username="admin",
        email="admin@integr8scode.com",
        password=admin_password,
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
    asyncio.run(seed_users(Settings()))
