"""
Consumer group definitions for Kafka consumers.

This module centralizes consumer group names and their associated topics,
ensuring consistency across the application.
"""
from enum import StrEnum
from typing import Dict, List

from app.schemas_avro.event_schemas import EventType, KafkaTopic, get_topic_for_event


class GroupId(StrEnum):
    """Consumer group identifiers used throughout the system."""
    
    EXECUTION_COORDINATOR = "execution-coordinator"
    K8S_WORKER = "k8s-worker"
    POD_MONITOR = "pod-monitor"
    RESULT_PROCESSOR = "result-processor"
    SAGA_ORCHESTRATOR = "saga-orchestrator"
    EVENT_PROJECTIONS = "event-projections"
    EVENT_STORE_CONSUMER = "event-store-consumer"
    WEBSOCKET_GATEWAY = "websocket-gateway"
    NOTIFICATION_SERVICE = "notification-service"
    DLQ_PROCESSOR = "dlq-processor"


# Mapping of consumer groups to their subscribed topics
CONSUMER_GROUP_TOPICS: Dict[GroupId, List[str]] = {
    GroupId.EXECUTION_COORDINATOR: [
        get_topic_for_event(EventType.EXECUTION_REQUESTED).value,
        get_topic_for_event(EventType.EXECUTION_COMPLETED).value,
        get_topic_for_event(EventType.EXECUTION_FAILED).value,
        get_topic_for_event(EventType.EXECUTION_CANCELLED).value
    ],
    GroupId.K8S_WORKER: [
        get_topic_for_event(EventType.EXECUTION_STARTED).value
    ],
    GroupId.POD_MONITOR: [
        get_topic_for_event(EventType.POD_CREATED).value,
        get_topic_for_event(EventType.POD_RUNNING).value,
        get_topic_for_event(EventType.POD_SUCCEEDED).value,
        get_topic_for_event(EventType.POD_FAILED).value
    ],
    GroupId.RESULT_PROCESSOR: [
        get_topic_for_event(EventType.EXECUTION_COMPLETED).value,
        get_topic_for_event(EventType.EXECUTION_FAILED).value,
        get_topic_for_event(EventType.EXECUTION_TIMEOUT).value
    ],
    GroupId.SAGA_ORCHESTRATOR: [
        KafkaTopic.SAGA_EVENTS.value
    ],
    GroupId.EVENT_PROJECTIONS: [
        # Event projections consume all events
        get_topic_for_event(EventType.EXECUTION_REQUESTED).value,
        get_topic_for_event(EventType.EXECUTION_STARTED).value,
        get_topic_for_event(EventType.EXECUTION_COMPLETED).value,
        get_topic_for_event(EventType.EXECUTION_FAILED).value,
        get_topic_for_event(EventType.EXECUTION_TIMEOUT).value,
        get_topic_for_event(EventType.EXECUTION_CANCELLED).value,
        get_topic_for_event(EventType.POD_CREATED).value,
        get_topic_for_event(EventType.POD_RUNNING).value,
        get_topic_for_event(EventType.POD_SUCCEEDED).value,
        get_topic_for_event(EventType.POD_FAILED).value,
        get_topic_for_event(EventType.USER_SETTINGS_UPDATED).value,
        get_topic_for_event(EventType.USER_PREFERENCES_UPDATED).value
    ],
    GroupId.WEBSOCKET_GATEWAY: [
        get_topic_for_event(EventType.EXECUTION_REQUESTED).value,
        get_topic_for_event(EventType.EXECUTION_STARTED).value,
        get_topic_for_event(EventType.EXECUTION_COMPLETED).value,
        get_topic_for_event(EventType.EXECUTION_FAILED).value,
        get_topic_for_event(EventType.POD_CREATED).value,
        get_topic_for_event(EventType.POD_RUNNING).value,
        get_topic_for_event(EventType.RESULT_STORED).value
    ],
    GroupId.NOTIFICATION_SERVICE: [
        get_topic_for_event(EventType.NOTIFICATION_CREATED).value,
        get_topic_for_event(EventType.EXECUTION_COMPLETED).value,
        get_topic_for_event(EventType.EXECUTION_FAILED).value
    ],
    GroupId.DLQ_PROCESSOR: [
        KafkaTopic.DEAD_LETTER_QUEUE.value
    ]
}


def get_consumer_group_topics(group: GroupId) -> List[str]:
    """
    Get the list of topics for a consumer group.
    
    Args:
        group: The consumer group
        
    Returns:
        List of topic names the group subscribes to
    """
    return CONSUMER_GROUP_TOPICS.get(group, [])


def get_all_consumer_groups() -> List[GroupId]:
    """
    Get all defined consumer groups.
    
    Returns:
        List of all consumer groups
    """
    return list(GroupId)


def get_consumer_groups_with_topics() -> List[tuple[str, List[str]]]:
    """
    Get all consumer groups with their associated topics.
    
    Returns:
        List of tuples containing (group_id, topics)
    """
    return [
        (group.value, get_consumer_group_topics(group))
        for group in GroupId
        if get_consumer_group_topics(group)  # Only include groups with topics
    ]
