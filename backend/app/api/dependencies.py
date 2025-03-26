from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import Settings, get_settings
from app.db.mongodb import get_database


def get_settings_dependency() -> Settings:
    return get_settings()


def get_db_dependency() -> AsyncIOMotorDatabase:
    return get_database()
