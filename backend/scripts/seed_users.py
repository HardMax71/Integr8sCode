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
import os
from datetime import datetime, timezone

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def upsert_user(
    db: AsyncIOMotorDatabase,
    username: str,
    email: str,
    password: str,
    role: str,
    is_superuser: bool,
) -> None:
    """Create user or update if exists."""
    existing = await db.users.find_one({"username": username})

    if existing:
        print(f"User '{username}' exists - updating role={role}, is_superuser={is_superuser}")
        await db.users.update_one(
            {"username": username},
            {"$set": {
                "role": role,
                "is_superuser": is_superuser,
                "is_active": True,
                "updated_at": datetime.now(timezone.utc)
            }}
        )
    else:
        print(f"Creating user '{username}' (role={role}, is_superuser={is_superuser})")
        await db.users.insert_one({
            "_id": ObjectId(),
            "user_id": str(ObjectId()),
            "username": username,
            "email": email,
            "hashed_password": pwd_context.hash(password),
            "role": role,
            "is_active": True,
            "is_superuser": is_superuser,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        })


async def seed_users() -> None:
    mongodb_url = os.getenv("MONGODB_URL", "mongodb://mongo:27017/integr8scode")
    print("Connecting to MongoDB...")

    client: AsyncIOMotorClient = AsyncIOMotorClient(mongodb_url)
    db_name = mongodb_url.rstrip("/").split("/")[-1].split("?")[0] or "integr8scode"
    db = client[db_name]

    # Default user
    await upsert_user(
        db,
        username="user",
        email="user@integr8scode.com",
        password=os.getenv("DEFAULT_USER_PASSWORD", "user123"),
        role="user",
        is_superuser=False
    )

    # Admin user
    await upsert_user(
        db,
        username="admin",
        email="admin@integr8scode.com",
        password=os.getenv("ADMIN_USER_PASSWORD", "admin123"),
        role="admin",
        is_superuser=True
    )

    print("\n" + "=" * 50)
    print("SEEDED USERS:")
    print("=" * 50)
    print("Default: user / user123  (or DEFAULT_USER_PASSWORD)")
    print("Admin:   admin / admin123 (or ADMIN_USER_PASSWORD)")
    print("=" * 50)

    client.close()


if __name__ == "__main__":
    asyncio.run(seed_users())
