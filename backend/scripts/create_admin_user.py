#!/usr/bin/env python3
"""Create an admin user directly in MongoDB"""

import asyncio
from datetime import datetime, timezone

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def create_admin_user() -> None:
    # Connect to MongoDB
    client: AsyncIOMotorClient = AsyncIOMotorClient("mongodb://root:rootpassword@mongo:27017/integr8scode?authSource=admin")
    db = client.integr8scode

    # User details
    username = "admin"
    email = "admin@integr8scode.com"
    password = "admin123"

    # Check if user already exists
    existing = await db.users.find_one({"username": username})
    if existing:
        print(f"User '{username}' already exists. Updating to admin role...")
        result = await db.users.update_one(
            {"username": username},
            {"$set": {
                "role": "admin",
                "is_superuser": True,
                "is_active": True,
                "updated_at": datetime.now(timezone.utc)
            }}
        )
        print(f"Updated: {result.modified_count} document(s)")
    else:
        # Create new admin user
        hashed_password = pwd_context.hash(password)
        user_doc = {
            "_id": ObjectId(),
            "user_id": str(ObjectId()),
            "username": username,
            "email": email,
            "hashed_password": hashed_password,
            "role": "admin",
            "is_active": True,
            "is_superuser": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }

        insert_result = await db.users.insert_one(user_doc)
        print(f"Created admin user '{username}' with ID: {insert_result.inserted_id}")

    print("\nAdmin credentials:")
    print(f"Username: {username}")
    print(f"Password: {password}")
    print(f"Email: {email}")

    client.close()

if __name__ == "__main__":
    asyncio.run(create_admin_user())
