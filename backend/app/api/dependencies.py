# app/api/dependencies.py
from app.config import Settings, get_settings
from app.core.logging import logger
from app.db.mongodb import DatabaseManager
from fastapi import HTTPException, Request, status
from motor.motor_asyncio import AsyncIOMotorDatabase


def get_settings_dependency() -> Settings:
    return get_settings()

def get_db_dependency(request: Request) -> AsyncIOMotorDatabase:
    """
    Dependency function to get the database handle from the DatabaseManager
    stored in the application state.
    """
    try:
        db_manager: DatabaseManager = request.app.state.db_manager
        return db_manager.get_database()  # type: ignore
    except AttributeError as e:
        # This signifies a critical setup error: lifespan didn't set the state.
        logger.critical("DatabaseManager not found in app state. Application startup likely failed.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error: Database service not available.",
        ) from e
    except RuntimeError as e:
         # This signifies get_database was called when db is None (shouldn't happen if connect succeeded)
         logger.error(f"Error retrieving database handle: {e}")
         raise HTTPException(
             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
             detail="Internal server error: Database connection issue.",
         ) from e
