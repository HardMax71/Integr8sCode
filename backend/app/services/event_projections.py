"""Event store projections for optimized querying"""

import asyncio
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel, UpdateOne

from app.core.logging import logger
from app.core.metrics import EVENT_PROJECTION_UPDATES
from app.db.mongodb import DatabaseManager
from app.schemas_avro.event_schemas import EventType


class ProjectionStatus(Enum):
    """Projection processing status"""
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    REBUILDING = "rebuilding"


class ProjectionDefinition:
    """Defines a projection's configuration and processing logic"""

    def __init__(
            self,
            name: str,
            description: str,
            source_events: List[str],
            output_collection: str,
            process_event: Callable,
            rebuild_aggregation: Optional[List[Dict[str, Any]]] = None,
            indexes: Optional[List[IndexModel]] = None,
            refresh_interval: int = 300
    ):
        self.name = name
        self.description = description
        self.source_events = source_events
        self.output_collection = output_collection
        self.process_event = process_event
        self.rebuild_aggregation = rebuild_aggregation
        self.indexes = indexes or []
        self.refresh_interval = refresh_interval


class EventProjectionService:
    """Manages event projections for query optimization"""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager
        db = db_manager.db
        if db is None:
            raise ValueError("Database not initialized")
        self.db: AsyncIOMotorDatabase = db
        self.projections: Dict[str, ProjectionDefinition] = {}
        self.projection_tasks: Dict[str, asyncio.Task] = {}
        self._initialized = False
        self._shutdown = False

    async def initialize(self) -> None:
        """Initialize projection service and register default projections"""
        if self._initialized:
            return

        # Register built-in projections
        await self._register_default_projections()

        # Create projection metadata collection
        await self._ensure_projection_metadata()

        self._initialized = True
        logger.info("Event projection service initialized")

    async def _ensure_projection_metadata(self) -> None:
        """Ensure projection metadata collection exists with indexes"""
        collection = self.db.projection_metadata

        indexes = [
            IndexModel([("name", ASCENDING)], unique=True),
            IndexModel([("status", ASCENDING)]),
            IndexModel([("last_updated", DESCENDING)])
        ]

        await collection.create_indexes(indexes)

    async def _register_default_projections(self) -> None:
        """Register default projections"""

        # 1. Execution Summary Projection
        self.register_projection(ProjectionDefinition(
            name="execution_summary",
            description="Summary of executions by user and status",
            source_events=[
                str(EventType.EXECUTION_REQUESTED),
                str(EventType.EXECUTION_COMPLETED),
                str(EventType.EXECUTION_FAILED),
                str(EventType.EXECUTION_TIMEOUT),
                str(EventType.EXECUTION_CANCELLED)
            ],
            output_collection="projection_execution_summary",
            process_event=self._process_execution_summary,
            rebuild_aggregation=[
                {
                    "$match": {
                        "event_type": {
                            "$in": [str(EventType.EXECUTION_REQUESTED), str(EventType.EXECUTION_COMPLETED),
                                    str(EventType.EXECUTION_FAILED), str(EventType.EXECUTION_TIMEOUT),
                                    str(EventType.EXECUTION_CANCELLED)]
                        }
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "user_id": "$metadata.user_id",
                            "date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}}
                        },
                        "total": {"$sum": 1},
                        "completed": {
                            "$sum": {"$cond": [{"$eq": ["$event_type", str(EventType.EXECUTION_COMPLETED)]}, 1, 0]}
                        },
                        "failed": {
                            "$sum": {"$cond": [{"$eq": ["$event_type", str(EventType.EXECUTION_FAILED)]}, 1, 0]}
                        },
                        "timeout": {
                            "$sum": {"$cond": [{"$eq": ["$event_type", str(EventType.EXECUTION_TIMEOUT)]}, 1, 0]}
                        },
                        "cancelled": {
                            "$sum": {"$cond": [{"$eq": ["$event_type", str(EventType.EXECUTION_CANCELLED)]}, 1, 0]}
                        },
                        "avg_duration": {"$avg": "$payload.duration_seconds"},
                        "languages": {"$addToSet": "$payload.language"}
                    }
                }
            ],
            indexes=[
                IndexModel([("_id.user_id", ASCENDING), ("_id.date", DESCENDING)]),
                IndexModel([("_id.date", DESCENDING)])
            ]
        ))

        # 2. User Activity Projection
        self.register_projection(ProjectionDefinition(
            name="user_activity",
            description="User activity timeline with execution counts",
            source_events=[str(EventType.EXECUTION_REQUESTED)],
            output_collection="projection_user_activity",
            process_event=self._process_user_activity,
            rebuild_aggregation=[
                {
                    "$match": {"event_type": str(EventType.EXECUTION_REQUESTED)}
                },
                {
                    "$group": {
                        "_id": {
                            "user_id": "$metadata.user_id",
                            "hour": {
                                "$dateToString": {
                                    "format": "%Y-%m-%d-%H",
                                    "date": "$timestamp"
                                }
                            }
                        },
                        "execution_count": {"$sum": 1},
                        "languages": {"$addToSet": "$payload.language"},
                        "first_execution": {"$min": "$timestamp"},
                        "last_execution": {"$max": "$timestamp"}
                    }
                }
            ],
            indexes=[
                IndexModel([("_id.user_id", ASCENDING), ("_id.hour", DESCENDING)]),
                IndexModel([("execution_count", DESCENDING)])
            ]
        ))

        # 3. Error Analysis Projection
        self.register_projection(ProjectionDefinition(
            name="error_analysis",
            description="Analysis of execution errors by type and language",
            source_events=[str(EventType.EXECUTION_FAILED), str(EventType.EXECUTION_TIMEOUT)],
            output_collection="projection_error_analysis",
            process_event=self._process_error_analysis,
            indexes=[
                IndexModel([("language", ASCENDING), ("error_type", ASCENDING)]),
                IndexModel([("count", DESCENDING)]),
                IndexModel([("last_seen", DESCENDING)])
            ]
        ))

        # 4. Language Usage Projection
        self.register_projection(ProjectionDefinition(
            name="language_usage",
            description="Language and version usage statistics",
            source_events=[str(EventType.EXECUTION_REQUESTED)],
            output_collection="projection_language_usage",
            process_event=self._process_language_usage,
            indexes=[
                IndexModel([("language", ASCENDING), ("version", ASCENDING)]),
                IndexModel([("usage_count", DESCENDING)]),
                IndexModel([("last_used", DESCENDING)])
            ]
        ))

        # 5. Performance Metrics Projection
        self.register_projection(ProjectionDefinition(
            name="performance_metrics",
            description="Execution performance metrics by hour",
            source_events=[str(EventType.EXECUTION_COMPLETED)],
            output_collection="projection_performance_metrics",
            process_event=self._process_performance_metrics,
            indexes=[
                IndexModel([("hour", DESCENDING)]),
                IndexModel([("language", ASCENDING), ("hour", DESCENDING)])
            ],
            refresh_interval=3600  # Update hourly
        ))

        # 6. User Settings Trends Projection
        self.register_projection(ProjectionDefinition(
            name="settings_trends",
            description="Popular settings and preferences trends",
            source_events=[
                str(EventType.USER_SETTINGS_UPDATED),
                str(EventType.USER_PREFERENCES_UPDATED),
                str(EventType.USER_THEME_CHANGED),
                str(EventType.USER_LANGUAGE_CHANGED),
                str(EventType.USER_NOTIFICATION_SETTINGS_UPDATED),
                str(EventType.USER_EDITOR_SETTINGS_UPDATED)
            ],
            output_collection="projection_settings_trends",
            process_event=self._process_settings_trends,
            indexes=[
                IndexModel([("setting_type", ASCENDING), ("value", ASCENDING)]),
                IndexModel([("count", DESCENDING)]),
                IndexModel([("last_updated", DESCENDING)])
            ],
            refresh_interval=3600  # Update hourly
        ))

    def register_projection(self, projection: ProjectionDefinition) -> None:
        """Register a new projection"""
        self.projections[projection.name] = projection
        logger.info(f"Registered projection: {projection.name}")

    def get_projection_names(self) -> list[str]:
        """Get all registered projection names."""
        return list(self.projections.keys())

    async def start_projection(self, name: str) -> None:
        """Start processing a projection"""
        if name not in self.projections:
            raise ValueError(f"Unknown projection: {name}")

        if name in self.projection_tasks:
            logger.warning(f"Projection {name} is already running")
            return

        projection = self.projections[name]

        # Create indexes
        await self._create_projection_indexes(projection)

        # Start processing task
        task = asyncio.create_task(self._process_projection(name))
        self.projection_tasks[name] = task

        # Update metadata with initial last_processed timestamp
        await self._update_projection_metadata(
            name,
            ProjectionStatus.ACTIVE,
            last_processed=datetime.now(timezone.utc)
        )

        logger.info(f"Started projection: {name}")

    async def stop_projection(self, name: str) -> None:
        """Stop processing a projection"""
        if name in self.projection_tasks:
            task = self.projection_tasks[name]
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass

            del self.projection_tasks[name]

        await self._update_projection_metadata(name, ProjectionStatus.PAUSED)
        logger.info(f"Stopped projection: {name}")

    async def rebuild_projection(self, name: str) -> None:
        """Rebuild a projection from scratch"""
        if name not in self.projections:
            raise ValueError(f"Unknown projection: {name}")

        projection = self.projections[name]

        # Stop if running
        await self.stop_projection(name)

        # Update status
        await self._update_projection_metadata(name, ProjectionStatus.REBUILDING)

        try:
            # Clear existing data
            await self.db[projection.output_collection].delete_many({})

            # Rebuild using aggregation if available
            if projection.rebuild_aggregation:
                logger.info(f"Rebuilding projection {name} using aggregation")

                pipeline = projection.rebuild_aggregation + [
                    {"$out": projection.output_collection}
                ]

                await self.db.events.aggregate(pipeline).to_list(None)
            else:
                # Process all historical events
                logger.info(f"Rebuilding projection {name} by replaying events")

                cursor = self.db.events.find({
                    "event_type": {"$in": projection.source_events}
                }).sort("timestamp", ASCENDING)

                batch = []
                async for event in cursor:
                    result = await projection.process_event(event, self.db)
                    if result:
                        batch.append(result)

                    if len(batch) >= 1000:
                        await self._write_projection_batch(projection.output_collection, batch)
                        batch = []

                if batch:
                    await self._write_projection_batch(projection.output_collection, batch)

            # Create indexes
            await self._create_projection_indexes(projection)

            # Update metadata
            await self._update_projection_metadata(name, ProjectionStatus.ACTIVE)

            logger.info(f"Completed rebuilding projection: {name}")

        except Exception as e:
            logger.error(f"Error rebuilding projection {name}: {e}")
            await self._update_projection_metadata(name, ProjectionStatus.ERROR, str(e))
            raise

    async def _process_projection(self, name: str) -> None:
        """Process events for a projection"""
        projection = self.projections[name]
        last_timestamp = await self._get_last_processed_timestamp(name)

        while not self._shutdown:
            try:
                # Process new events
                processed = await self._process_new_events(projection, last_timestamp)

                if processed > 0:
                    EVENT_PROJECTION_UPDATES.labels(
                        projection_name=name,
                        status="success"
                    ).inc(processed)

                # Update last processed timestamp regardless of whether events were found
                # This shows the projection is actively checking for new events
                last_timestamp = datetime.now(timezone.utc)
                await self._update_projection_metadata(
                    name,
                    ProjectionStatus.ACTIVE,
                    last_processed=last_timestamp
                )

                # Wait before next check
                await asyncio.sleep(min(projection.refresh_interval, 60))

            except asyncio.CancelledError:
                logger.info(f"Projection {name} processing cancelled")
                break
            except Exception as e:
                logger.error(f"Error processing projection {name}: {e}")
                EVENT_PROJECTION_UPDATES.labels(
                    projection_name=name,
                    status="error"
                ).inc()

                await self._update_projection_metadata(name, ProjectionStatus.ERROR, str(e))
                await asyncio.sleep(60)  # Wait before retry

    async def _process_new_events(
            self,
            projection: ProjectionDefinition,
            since: datetime | None
    ) -> int:
        """Process new events for a projection"""
        query: Dict[str, Any] = {
            "event_type": {"$in": projection.source_events}
        }

        if since:
            query["timestamp"] = {"$gt": since}

        logger.info(f"Querying events for projection {projection.name}: {query}")
        cursor = self.db.events.find(query).sort("timestamp", ASCENDING).limit(1000)

        processed = 0
        batch = []

        async for event in cursor:
            logger.debug(f"Processing event for {projection.name}: {event.get('event_type')} - {event.get('event_id')}")
            result = await projection.process_event(event, self.db)
            if result:
                batch.append(result)

            processed += 1

            if len(batch) >= 100:
                await self._write_projection_batch(projection.output_collection, batch)
                batch = []

        if batch:
            await self._write_projection_batch(projection.output_collection, batch)

        if processed > 0:
            logger.info(f"Processed {processed} events for projection {projection.name}")

        return processed

    async def _write_projection_batch(self,
                                      collection_name: str,
                                      batch: List[Dict[str, Any]]) -> None:
        """Write a batch of projection updates"""
        if not batch:
            return

        collection = self.db[collection_name]

        # Group by operation type
        inserts = []
        updates = []

        for item in batch:
            if "_id" in item:
                updates.append(item)
            else:
                inserts.append(item)

        # Perform bulk operations
        if inserts:
            await collection.insert_many(inserts)

        if updates:
            operations = []
            for update in updates:
                # Extract _id and separate update operators
                doc_id = update.pop("_id")

                # If update contains MongoDB operators, use them directly
                # Otherwise wrap in $set
                has_operators = any(key.startswith("$") for key in update.keys())

                if has_operators:
                    update_ops = update
                else:
                    update_ops = {"$set": update}

                # Create UpdateOne operation object
                operations.append(
                    UpdateOne(
                        filter={"_id": doc_id},
                        update=update_ops,
                        upsert=True
                    )
                )

            await collection.bulk_write(operations)

    async def _create_projection_indexes(self, projection: ProjectionDefinition) -> None:
        """Create indexes for a projection"""
        if projection.indexes:
            collection = self.db[projection.output_collection]
            await collection.create_indexes(projection.indexes)

    async def _get_last_processed_timestamp(self, name: str) -> datetime | None:
        """Get the last processed timestamp for a projection"""
        metadata = await self.db.projection_metadata.find_one({"name": name})
        return metadata.get("last_processed", None) if metadata else None

    async def _update_projection_metadata(
            self,
            name: str,
            status: ProjectionStatus,
            error: str | None = None,
            last_processed: datetime | None = None
    ) -> None:
        """Update projection metadata"""
        update: Dict[str, Any] = {
            "name": name,
            "status": status.value,
            "last_updated": datetime.now(timezone.utc)
        }

        if error:
            update["error"] = error
        else:
            update["error"] = None

        if last_processed:
            update["last_processed"] = last_processed

        if name in self.projections:
            projection = self.projections[name]
            update["description"] = projection.description
            update["source_events"] = projection.source_events
            update["output_collection"] = projection.output_collection

        await self.db.projection_metadata.update_one(
            {"name": name},
            {"$set": update},
            upsert=True
        )

    # Projection processing functions

    async def _process_execution_summary(
            self,
            event: Dict[str, Any],
            db: AsyncIOMotorDatabase
    ) -> Optional[Dict[str, Any]]:
        """Process events for execution summary projection"""
        user_id = event.get("metadata", {}).get("user_id")
        if not user_id:
            return None

        # Store timestamp as number, let frontend handle date formatting
        timestamp = event["timestamp"]

        update = {
            "$inc": {"total": 1}
        }

        if event["event_type"] == str(EventType.EXECUTION_COMPLETED):
            update["$inc"]["completed"] = 1
            if duration := event.get("payload", {}).get("duration_seconds"):
                update["$inc"]["total_duration"] = duration
                update["$inc"]["duration_count"] = 1
        elif event["event_type"] == str(EventType.EXECUTION_FAILED):
            update["$inc"]["failed"] = 1
        elif event["event_type"] == str(EventType.EXECUTION_TIMEOUT):
            update["$inc"]["timeout"] = 1
        elif event["event_type"] == str(EventType.EXECUTION_CANCELLED):
            update["$inc"]["cancelled"] = 1

        # ExecutionRequestedEvent has language at root level
        language = event.get("language") or event.get("payload", {}).get("language")
        if language:
            update["$addToSet"] = {"languages": language}

        return {
            "_id": {"user_id": user_id, "timestamp": timestamp},
            **update
        }

    async def _process_user_activity(
            self,
            event: Dict[str, Any],
            db: AsyncIOMotorDatabase
    ) -> Optional[Dict[str, Any]]:
        """Process events for user activity projection"""
        user_id = event.get("metadata", {}).get("user_id")
        if not user_id:
            return None

        timestamp = event["timestamp"]  # Keep as numeric timestamp

        # ExecutionRequestedEvent has language at root level, not in payload
        logger.info(f"Processing user_activity event: {json.dumps(event, default=str)}")
        language = event.get("language") or event.get("payload", {}).get("language")

        return {
            "_id": {"user_id": user_id, "timestamp": timestamp},
            "$inc": {"execution_count": 1},
            "$addToSet": {"languages": language},
            "$min": {"first_execution": event["timestamp"]},
            "$max": {"last_execution": event["timestamp"]}
        }

    async def _process_error_analysis(
            self,
            event: Dict[str, Any],
            db: AsyncIOMotorDatabase
    ) -> Optional[Dict[str, Any]]:
        """Process events for error analysis projection"""
        language = event.get("payload", {}).get("language", "unknown")

        error_type = "timeout" if event["event_type"] == str(EventType.EXECUTION_TIMEOUT) else "runtime_error"
        error_message = event.get("payload", {}).get("error", "Unknown error")

        # Extract error type from message if possible
        if "Error:" in error_message:
            error_type = error_message.split("Error:")[0].strip()

        return {
            "_id": {
                "language": language,
                "error_type": error_type,
                "timestamp": event["timestamp"]
            },
            "$inc": {"count": 1},
            "$set": {"last_seen": event["timestamp"]},
            "$addToSet": {"sample_errors": {
                "$each": [error_message],
                "$slice": -5  # Keep only last 5 samples
            }}
        }

    async def _process_language_usage(
            self,
            event: Dict[str, Any],
            db: AsyncIOMotorDatabase
    ) -> Optional[Dict[str, Any]]:
        """Process events for language usage projection"""
        # ExecutionRequestedEvent has language fields at root level, not in payload
        logger.info(f"Processing language_usage event: {json.dumps(event, default=str)}")
        language = event.get("language") or event.get("payload", {}).get("language")
        version = event.get("language_version") or event.get("payload", {}).get("language_version", "unknown")

        if not language:
            return None

        return {
            "_id": {
                "language": language,
                "version": version,
                "timestamp": event["timestamp"]
            },
            "$inc": {"usage_count": 1},
            "$set": {"last_used": event["timestamp"]},
            "$addToSet": {"users": event.get("metadata", {}).get("user_id")}
        }

    async def _process_performance_metrics(
            self,
            event: Dict[str, Any],
            db: AsyncIOMotorDatabase
    ) -> Optional[Dict[str, Any]]:
        """Process events for performance metrics projection"""
        duration = event.get("payload", {}).get("duration_seconds")
        if not duration:
            return None

        language = event.get("payload", {}).get("language", "unknown")
        hour = event["timestamp"].replace(minute=0, second=0, microsecond=0)

        return {
            "_id": {
                "hour": hour,
                "language": language
            },
            "$inc": {
                "execution_count": 1,
                "total_duration": duration
            },
            "$min": {"min_duration": duration},
            "$max": {"max_duration": duration},
            "$push": {
                "durations": {
                    "$each": [duration],
                    "$slice": -100  # Keep last 100 for percentile calculation
                }
            }
        }

    async def _process_settings_trends(
            self,
            event: Dict[str, Any],
            db: AsyncIOMotorDatabase
    ) -> Optional[Dict[str, Any]]:
        """Process events for settings trends projection"""
        payload = event.get("payload", {})
        changes = payload.get("changes", [])

        if not changes:
            return None

        # Extract setting type from event type
        event_type = event["event_type"]
        setting_type = "general"

        if "theme" in event_type:
            setting_type = "theme"
        elif "language" in event_type:
            setting_type = "language"
        elif "notification" in event_type:
            setting_type = "notifications"
        elif "editor" in event_type:
            setting_type = "editor"
        elif "preferences" in event_type:
            setting_type = "preferences"

        # Process each change
        updates = []
        for change in changes:
            field_path = change.get("field_path", "")
            new_value = change.get("new_value")

            # Convert complex values to string for aggregation
            if isinstance(new_value, (dict, list)):
                value_str = json.dumps(new_value, sort_keys=True)
            else:
                value_str = str(new_value)

            updates.append({
                "_id": {
                    "setting_type": setting_type,
                    "field": field_path,
                    "value": value_str,
                    "timestamp": event["timestamp"]
                },
                "$inc": {"count": 1},
                "$set": {"last_updated": event["timestamp"]},
                "$addToSet": {"users": event.get("metadata", {}).get("user_id")}
            })

        # Return the first update for now (batch processing will handle multiple)
        return updates[0] if updates else None

    async def get_projection_status(self) -> List[Dict[str, Any]]:
        """Get status of all projections"""
        cursor = self.db.projection_metadata.find({})
        return await cursor.to_list(None)

    async def shutdown(self) -> None:
        """Shutdown projection service"""
        self._shutdown = True

        # Cancel all running tasks
        for _, task in self.projection_tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self.projection_tasks.clear()
        logger.info("Event projection service shut down")


class EventProjectionManager:
    """Manages the lifecycle of EventProjectionService instance"""

    def __init__(self) -> None:
        self._service: Optional[EventProjectionService] = None

    async def get_service(self, db_manager: DatabaseManager) -> EventProjectionService:
        """Get or create projection service instance"""
        if self._service is None:
            self._service = EventProjectionService(db_manager)
            await self._service.initialize()
        return self._service

    async def shutdown(self) -> None:
        """Shutdown the projection service"""
        if self._service:
            await self._service.shutdown()
            self._service = None
