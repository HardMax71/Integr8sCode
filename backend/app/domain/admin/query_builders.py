"""MongoDB query and aggregation pipeline builders.

This module provides type-safe builders for MongoDB queries and aggregation pipelines.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.domain.admin.event_models import EventFields


class AggregationStages:
    """Common aggregation pipeline stages."""
    
    @staticmethod
    def match(conditions: Dict[str, Any]) -> Dict[str, Any]:
        """Create a $match stage."""
        return {"$match": conditions}
    
    @staticmethod
    def group(group_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Create a $group stage."""
        return {"$group": group_spec}
    
    @staticmethod
    def sort(sort_spec: Dict[str, int]) -> Dict[str, Any]:
        """Create a $sort stage."""
        return {"$sort": sort_spec}
    
    @staticmethod
    def limit(count: int) -> Dict[str, Any]:
        """Create a $limit stage."""
        return {"$limit": count}
    
    @staticmethod
    def project(projection: Dict[str, Any]) -> Dict[str, Any]:
        """Create a $project stage."""
        return {"$project": projection}
    
    @staticmethod
    def add_to_set(field: str) -> Dict[str, str]:
        """Create an $addToSet accumulator."""
        return {"$addToSet": field}
    
    @staticmethod
    def sum(value: int | str = 1) -> Dict[str, int | str]:
        """Create a $sum accumulator."""
        return {"$sum": value}
    
    @staticmethod
    def avg(field: str) -> Dict[str, str]:
        """Create an $avg accumulator."""
        return {"$avg": field}
    
    @staticmethod
    def size(field: str) -> Dict[str, str]:
        """Create a $size operator."""
        return {"$size": field}
    
    @staticmethod
    def date_to_string(date_field: str, format: str = "%Y-%m-%d-%H") -> Dict[str, Any]:
        """Create a $dateToString expression."""
        return {
            "$dateToString": {
                "format": format,
                "date": date_field
            }
        }


class EventStatsAggregation:
    """Builder for event statistics aggregation pipelines."""
    
    @staticmethod
    def build_overview_pipeline(start_time: datetime) -> List[Dict[str, Any]]:
        """Build pipeline for event overview statistics."""
        return [
            AggregationStages.match({EventFields.TIMESTAMP: {"$gte": start_time}}),
            AggregationStages.group({
                "_id": None,
                "total_events": AggregationStages.sum(),
                "event_types": AggregationStages.add_to_set(f"${EventFields.EVENT_TYPE}"),
                "unique_users": AggregationStages.add_to_set(f"${EventFields.METADATA_USER_ID}"),
                "services": AggregationStages.add_to_set(f"${EventFields.METADATA_SERVICE_NAME}")
            }),
            AggregationStages.project({
                "_id": 0,
                "total_events": 1,
                "event_type_count": AggregationStages.size("$event_types"),
                "unique_user_count": AggregationStages.size("$unique_users"),
                "service_count": AggregationStages.size("$services")
            })
        ]
    
    @staticmethod
    def build_event_types_pipeline(start_time: datetime, limit: int = 10) -> List[Dict[str, Any]]:
        """Build pipeline for event type statistics."""
        return [
            AggregationStages.match({EventFields.TIMESTAMP: {"$gte": start_time}}),
            AggregationStages.group({
                "_id": f"${EventFields.EVENT_TYPE}",
                "count": AggregationStages.sum()
            }),
            AggregationStages.sort({"count": -1}),
            AggregationStages.limit(limit)
        ]
    
    @staticmethod
    def build_hourly_events_pipeline(start_time: datetime) -> List[Dict[str, Any]]:
        """Build pipeline for hourly event counts."""
        return [
            AggregationStages.match({EventFields.TIMESTAMP: {"$gte": start_time}}),
            AggregationStages.group({
                "_id": AggregationStages.date_to_string(f"${EventFields.TIMESTAMP}"),
                "count": AggregationStages.sum()
            }),
            AggregationStages.sort({"_id": 1})
        ]
    
    @staticmethod
    def build_top_users_pipeline(start_time: datetime, limit: int = 10) -> List[Dict[str, Any]]:
        """Build pipeline for top users by event count."""
        return [
            AggregationStages.match({EventFields.TIMESTAMP: {"$gte": start_time}}),
            AggregationStages.group({
                "_id": f"${EventFields.METADATA_USER_ID}",
                "count": AggregationStages.sum()
            }),
            AggregationStages.sort({"count": -1}),
            AggregationStages.limit(limit)
        ]
    
    @staticmethod
    def build_avg_duration_pipeline(start_time: datetime, event_type: str) -> List[Dict[str, Any]]:
        """Build pipeline for average execution duration."""
        return [
            AggregationStages.match({
                EventFields.TIMESTAMP: {"$gte": start_time},
                EventFields.EVENT_TYPE: event_type,
                EventFields.PAYLOAD_DURATION_SECONDS: {"$exists": True}
            }),
            AggregationStages.group({
                "_id": None,
                "avg_duration": AggregationStages.avg(f"${EventFields.PAYLOAD_DURATION_SECONDS}")
            })
        ]


class QueryBuilder:
    """Builder for MongoDB queries."""
    
    @staticmethod
    def regex_search(field: str, pattern: str, case_insensitive: bool = True) -> Dict[str, Any]:
        """Build regex search condition."""
        options = "i" if case_insensitive else ""
        return {field: {"$regex": pattern, "$options": options}}
    
    @staticmethod
    def time_range(field: str, start: Optional[datetime] = None, end: Optional[datetime] = None) -> Dict[str, Any]:
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
    def in_list(field: str, values: List[Any]) -> Dict[str, Any]:
        """Build IN condition."""
        return {field: {"$in": values}}
    
    @staticmethod
    def not_equal(field: str, value: Any) -> Dict[str, Any]:
        """Build not equal condition."""
        return {field: {"$ne": value}}
    
    @staticmethod
    def exists(field: str, exists: bool = True) -> Dict[str, Any]:
        """Build exists condition."""
        return {field: {"$exists": exists}}
    
    @staticmethod
    def or_conditions(conditions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build OR condition."""
        return {"$or": conditions}
    
    @staticmethod
    def and_conditions(conditions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build AND condition."""
        return {"$and": conditions}
