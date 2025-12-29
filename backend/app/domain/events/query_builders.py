from datetime import datetime
from typing import Any


class AggregationStages:
    @staticmethod
    def match(conditions: dict[str, Any]) -> dict[str, Any]:
        """Create a $match stage."""
        return {"$match": conditions}

    @staticmethod
    def group(group_spec: dict[str, Any]) -> dict[str, Any]:
        """Create a $group stage."""
        return {"$group": group_spec}

    @staticmethod
    def sort(sort_spec: dict[str, int]) -> dict[str, Any]:
        """Create a $sort stage."""
        return {"$sort": sort_spec}

    @staticmethod
    def limit(count: int) -> dict[str, Any]:
        """Create a $limit stage."""
        return {"$limit": count}

    @staticmethod
    def project(projection: dict[str, Any]) -> dict[str, Any]:
        """Create a $project stage."""
        return {"$project": projection}

    @staticmethod
    def add_to_set(field: str) -> dict[str, str]:
        """Create an $addToSet accumulator."""
        return {"$addToSet": field}

    @staticmethod
    def sum(value: int | str = 1) -> dict[str, int | str]:
        """Create a $sum accumulator."""
        return {"$sum": value}

    @staticmethod
    def avg(field: str) -> dict[str, str]:
        """Create an $avg accumulator."""
        return {"$avg": field}

    @staticmethod
    def size(field: str) -> dict[str, str]:
        """Create a $size operator."""
        return {"$size": field}

    @staticmethod
    def date_to_string(date_field: str, date_format: str = "%Y-%m-%d-%H") -> dict[str, Any]:
        """Create a $dateToString expression."""
        return {"$dateToString": {"format": date_format, "date": date_field}}


class EventStatsAggregation:
    @staticmethod
    def build_overview_pipeline(start_time: datetime) -> list[dict[str, Any]]:
        return [
            AggregationStages.match({"timestamp": {"$gte": start_time}}),
            AggregationStages.group(
                {
                    "_id": None,
                    "total_events": AggregationStages.sum(),
                    "event_types": AggregationStages.add_to_set("$event_type"),
                    "unique_users": AggregationStages.add_to_set("$metadata.user_id"),
                    "services": AggregationStages.add_to_set("$metadata.service_name"),
                }
            ),
            AggregationStages.project(
                {
                    "_id": 0,
                    "total_events": 1,
                    "event_type_count": AggregationStages.size("$event_types"),
                    "unique_user_count": AggregationStages.size("$unique_users"),
                    "service_count": AggregationStages.size("$services"),
                }
            ),
        ]

    @staticmethod
    def build_event_types_pipeline(start_time: datetime, limit: int = 10) -> list[dict[str, Any]]:
        return [
            AggregationStages.match({"timestamp": {"$gte": start_time}}),
            AggregationStages.group({"_id": "$event_type", "count": AggregationStages.sum()}),
            AggregationStages.sort({"count": -1}),
            AggregationStages.limit(limit),
        ]

    @staticmethod
    def build_hourly_events_pipeline(start_time: datetime) -> list[dict[str, Any]]:
        return [
            AggregationStages.match({"timestamp": {"$gte": start_time}}),
            AggregationStages.group(
                {"_id": AggregationStages.date_to_string("$timestamp"), "count": AggregationStages.sum()}
            ),
            AggregationStages.sort({"_id": 1}),
        ]

    @staticmethod
    def build_top_users_pipeline(start_time: datetime, limit: int = 10) -> list[dict[str, Any]]:
        return [
            AggregationStages.match({"timestamp": {"$gte": start_time}}),
            AggregationStages.group({"_id": "$metadata.user_id", "count": AggregationStages.sum()}),
            AggregationStages.sort({"count": -1}),
            AggregationStages.limit(limit),
        ]

    @staticmethod
    def build_avg_duration_pipeline(start_time: datetime, event_type: str) -> list[dict[str, Any]]:
        return [
            AggregationStages.match(
                {
                    "timestamp": {"$gte": start_time},
                    "event_type": event_type,
                    "payload.duration_seconds": {"$exists": True},
                }
            ),
            AggregationStages.group(
                {"_id": None, "avg_duration": AggregationStages.avg("$payload.duration_seconds")}
            ),
        ]


class QueryBuilder:
    @staticmethod
    def regex_search(field: str, pattern: str, case_insensitive: bool = True) -> dict[str, Any]:
        """Build regex search condition."""
        options = "i" if case_insensitive else ""
        return {field: {"$regex": pattern, "$options": options}}

    @staticmethod
    def time_range(field: str, start: datetime | None = None, end: datetime | None = None) -> dict[str, Any]:
        """Build time range condition."""
        if not start and not end:
            return {}

        condition = {}
        if start:
            condition["$gte"] = start
        if end:
            condition["$lte"] = end

        return {field: condition}

    @staticmethod
    def in_list(field: str, values: list[Any]) -> dict[str, Any]:
        """Build IN condition."""
        return {field: {"$in": values}}

    @staticmethod
    def not_equal(field: str, value: Any) -> dict[str, Any]:
        """Build not equal condition."""
        return {field: {"$ne": value}}

    @staticmethod
    def exists(field: str, exists: bool = True) -> dict[str, Any]:
        """Build exists condition."""
        return {field: {"$exists": exists}}

    @staticmethod
    def or_conditions(conditions: list[dict[str, Any]]) -> dict[str, Any]:
        """Build OR condition."""
        return {"$or": conditions}

    @staticmethod
    def and_conditions(conditions: list[dict[str, Any]]) -> dict[str, Any]:
        """Build AND condition."""
        return {"$and": conditions}
