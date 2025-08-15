"""Setup event projections for optimized queries"""

import asyncio
from typing import Any, Dict

from app.config import get_settings
from app.core.logging import logger
from app.db.repositories.event_repository import EventRepository
from app.schemas_avro.event_schemas import EventType
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

# Define projections
PROJECTIONS = [
    {
        "name": "execution_summary",
        "description": "Summary of executions by user and status",
        "pipeline": [
            {
                "$match": {
                    "event_type": {
                        "$in": [str(EventType.EXECUTION_STARTED), str(EventType.EXECUTION_COMPLETED),
                                str(EventType.EXECUTION_FAILED)]
                    }
                }
            },
            {
                "$sort": {"timestamp": 1}
            },
            {
                "$group": {
                    "_id": {
                        "execution_id": "$aggregate_id",
                        "user_id": "$metadata.user_id"
                    },
                    "first_event": {"$first": "$$ROOT"},
                    "last_event": {"$last": "$$ROOT"},
                    "events": {"$push": "$$ROOT"},
                    "event_count": {"$sum": 1}
                }
            },
            {
                "$project": {
                    "_id": "$_id.execution_id",
                    "user_id": "$_id.user_id",
                    "status": "$last_event.payload.status",
                    "language": "$first_event.payload.language",
                    "language_version": "$first_event.payload.language_version",
                    "started_at": "$first_event.timestamp",
                    "completed_at": {
                        "$cond": {
                            "if": {"$in": ["$last_event.payload.status", ["completed", "failed", "error"]]},
                            "then": "$last_event.timestamp",
                            "else": None
                        }
                    },
                    "duration_seconds": {
                        "$cond": {
                            "if": {"$in": ["$last_event.payload.status", ["completed", "failed", "error"]]},
                            "then": {
                                "$divide": [
                                    {"$subtract": ["$last_event.timestamp", "$first_event.timestamp"]},
                                    1000
                                ]
                            },
                            "else": None
                        }
                    },
                    "event_count": 1,
                    "last_updated": "$last_event.timestamp"
                }
            }
        ],
        "output_collection": "execution_summary"
    },
    {
        "name": "user_activity",
        "description": "User activity summary",
        "pipeline": [
            {
                "$match": {
                    "metadata.user_id": {"$exists": True, "$ne": None}
                }
            },
            {
                "$group": {
                    "_id": {
                        "user_id": "$metadata.user_id",
                        "date": {
                            "$dateToString": {
                                "format": "%Y-%m-%d",
                                "date": "$timestamp"
                            }
                        },
                        "event_type": "$event_type"
                    },
                    "count": {"$sum": 1},
                    "first_event": {"$min": "$timestamp"},
                    "last_event": {"$max": "$timestamp"}
                }
            },
            {
                "$group": {
                    "_id": {
                        "user_id": "$_id.user_id",
                        "date": "$_id.date"
                    },
                    "event_counts": {
                        "$push": {
                            "event_type": "$_id.event_type",
                            "count": "$count"
                        }
                    },
                    "total_events": {"$sum": "$count"},
                    "first_activity": {"$min": "$first_event"},
                    "last_activity": {"$max": "$last_event"}
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "user_id": "$_id.user_id",
                    "date": "$_id.date",
                    "event_counts": 1,
                    "total_events": 1,
                    "first_activity": 1,
                    "last_activity": 1,
                    "active_hours": {
                        "$divide": [
                            {"$subtract": ["$last_activity", "$first_activity"]},
                            3600000  # Convert to hours
                        ]
                    }
                }
            }
        ],
        "output_collection": "user_activity"
    },
    {
        "name": "error_summary",
        "description": "Summary of errors and failures",
        "pipeline": [
            {
                "$match": {
                    "$or": [
                        {"event_type": {"$regex": ".*\\.failed$"}},
                        {"event_type": {"$regex": ".*\\.error$"}},
                        {"payload.status": {"$in": ["failed", "error"]}}
                    ]
                }
            },
            {
                "$group": {
                    "_id": {
                        "event_type": "$event_type",
                        "error_type": {"$ifNull": ["$payload.error_type", "unknown"]},
                        "date": {
                            "$dateToString": {
                                "format": "%Y-%m-%d",
                                "date": "$timestamp"
                            }
                        }
                    },
                    "count": {"$sum": 1},
                    "sample_errors": {
                        "$push": {
                            "$cond": {
                                "if": {"$lt": [{"$rand": {}}, 0.1]},  # Sample 10%
                                "then": {
                                    "event_id": "$event_id",
                                    "error": "$payload.error",
                                    "timestamp": "$timestamp"
                                },
                                "else": "$$REMOVE"
                            }
                        }
                    }
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "event_type": "$_id.event_type",
                    "error_type": "$_id.error_type",
                    "date": "$_id.date",
                    "count": 1,
                    "sample_errors": {"$slice": ["$sample_errors", 5]}  # Keep max 5 samples
                }
            }
        ],
        "output_collection": "error_summary"
    }
]


async def create_projection(database: AsyncIOMotorDatabase, projection: Dict[str, Any]) -> None:
    """Create a single projection"""
    try:
        event_repo = EventRepository(database)

        logger.info(f"Creating projection: {projection['name']}")

        await event_repo.create_event_projection(
            name=projection["name"],
            pipeline=projection["pipeline"],
            output_collection=projection["output_collection"]
        )

        # Create indexes on output collection
        output_coll = database[projection["output_collection"]]

        if projection["name"] == "execution_summary":
            await output_coll.create_index([("user_id", 1)])
            await output_coll.create_index([("status", 1)])
            await output_coll.create_index([("started_at", -1)])

        elif projection["name"] == "user_activity":
            await output_coll.create_index([("user_id", 1), ("date", -1)])
            await output_coll.create_index([("date", -1)])

        elif projection["name"] == "error_summary":
            await output_coll.create_index([("date", -1)])
            await output_coll.create_index([("event_type", 1)])
            await output_coll.create_index([("error_type", 1)])

        logger.info(f"Successfully created projection: {projection['name']}")

    except Exception as e:
        logger.error(f"Failed to create projection {projection['name']}: {e}")
        raise


async def refresh_projections(database: AsyncIOMotorDatabase) -> None:
    """Refresh all projections"""
    for projection in PROJECTIONS:
        await create_projection(database, projection)


async def setup_projection_refresh_job(database: AsyncIOMotorDatabase) -> None:
    """Setup a scheduled job to refresh projections"""
    # This would typically be done with a task scheduler like Celery or APScheduler
    # For now, we'll just create the projections once
    await refresh_projections(database)


async def main() -> None:
    """Main migration function"""
    settings = get_settings()
    
    db_client: AsyncIOMotorClient = AsyncIOMotorClient(
        settings.MONGODB_URL,
        tz_aware=True,
        serverSelectionTimeoutMS=5000
    )
    db_name = settings.PROJECT_NAME + "_test" if settings.TESTING else settings.PROJECT_NAME
    database = db_client[db_name]

    try:
        # Verify connection
        await db_client.admin.command("ping")
        logger.info(f"Connected to database: {db_name}")

        # Initialize event repository to create indexes
        event_repo = EventRepository(database)
        await event_repo.initialize()
        logger.info("Event collection initialized")

        # Create projections
        await refresh_projections(database)
        logger.info("All projections created successfully")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        db_client.close()
        logger.info("Database connection closed")


if __name__ == "__main__":
    asyncio.run(main())
