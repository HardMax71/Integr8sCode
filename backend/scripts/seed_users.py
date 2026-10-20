#!/usr/bin/env python3
"""
Seed default users in MongoDB (idempotent - safe to run multiple times).

Creates:
  1. Default user (role=user) for testing/demo
  2. Admin user (role=admin, is_superuser=True) for administration
  3. The collector's monitoring user, with a role that can only read server and index stats

Also drops duplicate system settings documents, which an old get-or-insert race could create
and which would stop the unique settings_id index from building, and rewrites the stored theme
"auto" to its current name "system". The backend container runs this script before gunicorn
starts, and the worker starts once the backend is healthy.

Uses main Settings for MongoDB connection. Password env vars are script-specific and required:
  DEFAULT_USER_PASSWORD: Default user password
  ADMIN_USER_PASSWORD: Admin user password
  MONGO_MONITOR_USER, MONGO_MONITOR_PASSWORD: the collector's mongodb receiver login
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.asynchronous.mongo_client import AsyncMongoClient

from app.settings import Settings


async def upsert_user(
    db: AsyncDatabase[dict[str, Any]],
    pwd_hasher: PasswordHash,
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
                    "hashed_password": pwd_hasher.hash(password),
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
                "hashed_password": pwd_hasher.hash(password),
                "role": role,
                "is_active": True,
                "is_superuser": is_superuser,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )


async def drop_duplicate_system_settings(db: AsyncDatabase[dict[str, Any]]) -> None:
    """Keep only the most recently updated system settings document."""
    cursor = db.system_settings.find({"settings_id": "global"}, {"_id": 1}).sort("updated_at", -1).skip(1)
    stale = [doc["_id"] async for doc in cursor]
    if stale:
        print(f"Removing {len(stale)} duplicate system settings documents")
        await db.system_settings.delete_many({"_id": {"$in": stale}})


async def rename_auto_theme(db: AsyncDatabase[dict[str, Any]]) -> None:
    """The theme that follows the system was stored as "auto" before it became "system"; rewrite every stored copy."""
    renames = [
        (db.user_settings, {"theme": "auto"}, "theme"),
        (db.events, {"event_type": "user_settings_updated", "theme": "auto"}, "theme"),
        (db.events_archive, {"event_type": "user_settings_updated", "theme": "auto"}, "theme"),
        (db.dlq_messages, {"event.event_type": "user_settings_updated", "event.theme": "auto"}, "event.theme"),
    ]
    for collection, query, field in renames:
        result = await collection.update_many(query, {"$set": {field: "system"}})
        if result.modified_count:
            print(f"Renamed the auto theme to system in {result.modified_count} {collection.name} documents")


async def sync_monitor_user(client: AsyncMongoClient[dict[str, Any]], db_name: str, user: str, password: str) -> None:
    """Create or update the collector's mongodb receiver login; root fails $indexStats on admin.system.*."""
    admin = client.admin
    privileges = [
        {"resource": {"cluster": True}, "actions": ["serverStatus", "top"]},
        {"resource": {"db": db_name, "collection": ""}, "actions": ["dbStats", "indexStats", "listCollections"]},
    ]
    role_exists = (await admin.command("rolesInfo", "otelMonitor"))["roles"]
    await admin.command("updateRole" if role_exists else "createRole", "otelMonitor", privileges=privileges, roles=[])
    user_exists = (await admin.command("usersInfo", user))["users"]
    await admin.command("updateUser" if user_exists else "createUser", user, pwd=password, roles=["otelMonitor"])
    print(f"Synced monitoring user '{user}'")


async def seed_users(settings: Settings) -> None:
    """Seed default users using provided settings for MongoDB connection."""
    pwd_hasher = PasswordHash((BcryptHasher(rounds=settings.BCRYPT_ROUNDS),))
    default_password = os.environ["DEFAULT_USER_PASSWORD"]
    admin_password = os.environ["ADMIN_USER_PASSWORD"]

    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.MONGODB_URL.get_secret_value())
    db = client.get_default_database(default=settings.MONGO_DB)
    print(f"Connecting to MongoDB (database: {db.name})...")

    await drop_duplicate_system_settings(db)
    await rename_auto_theme(db)
    await sync_monitor_user(client, db.name, os.environ["MONGO_MONITOR_USER"], os.environ["MONGO_MONITOR_PASSWORD"])

    # Default user
    await upsert_user(
        db,
        pwd_hasher,
        username="user",
        email="user@integr8scode.com",
        password=default_password,
        role="user",
        is_superuser=False,
    )

    # Admin user
    await upsert_user(
        db,
        pwd_hasher,
        username="admin",
        email="admin@integr8scode.com",
        password=admin_password,
        role="admin",
        is_superuser=True,
    )

    print("Seeded users 'user' and 'admin', passwords from DEFAULT_USER_PASSWORD and ADMIN_USER_PASSWORD")

    await client.close()


if __name__ == "__main__":
    asyncio.run(seed_users(Settings()))
