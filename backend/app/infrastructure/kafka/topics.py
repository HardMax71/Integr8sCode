from typing import Any

from app.domain.enums.kafka import KafkaTopic


def get_all_topics() -> set[KafkaTopic]:
    """Get all Kafka topics."""
    return set(KafkaTopic)


def get_topic_configs() -> dict[KafkaTopic, dict[str, Any]]:
    """Get configuration for all Kafka topics."""
    return {
        # High-volume execution topics
        KafkaTopic.EXECUTION_EVENTS: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.EXECUTION_COMPLETED: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.EXECUTION_FAILED: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.EXECUTION_TIMEOUT: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.EXECUTION_REQUESTS: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.EXECUTION_COMMANDS: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "86400000",  # 1 day
                "compression.type": "gzip",
            }
        },
        KafkaTopic.EXECUTION_TASKS: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "86400000",  # 1 day
                "compression.type": "gzip",
            }
        },

        # Pod lifecycle topics
        KafkaTopic.POD_EVENTS: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "86400000",  # 1 day
                "compression.type": "gzip",
            }
        },
        KafkaTopic.POD_STATUS_UPDATES: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "86400000",  # 1 day
                "compression.type": "gzip",
            }
        },
        KafkaTopic.POD_RESULTS: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },

        # Result topics
        KafkaTopic.EXECUTION_RESULTS: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },

        # User topics
        KafkaTopic.USER_EVENTS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "2592000000",  # 30 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.USER_NOTIFICATIONS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.USER_SETTINGS_EVENTS: {
            "num_partitions": 3,
            "replication_factor": 1,
            "config": {
                "retention.ms": "2592000000",  # 30 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.USER_SETTINGS_THEME_EVENTS: {
            "num_partitions": 3,
            "replication_factor": 1,
            "config": {
                "retention.ms": "2592000000",  # 30 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.USER_SETTINGS_NOTIFICATION_EVENTS: {
            "num_partitions": 3,
            "replication_factor": 1,
            "config": {
                "retention.ms": "2592000000",  # 30 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.USER_SETTINGS_EDITOR_EVENTS: {
            "num_partitions": 3,
            "replication_factor": 1,
            "config": {
                "retention.ms": "2592000000",  # 30 days
                "compression.type": "gzip",
            }
        },

        # Script topics
        KafkaTopic.SCRIPT_EVENTS: {
            "num_partitions": 3,
            "replication_factor": 1,
            "config": {
                "retention.ms": "2592000000",  # 30 days
                "compression.type": "gzip",
            }
        },

        # Security topics
        KafkaTopic.SECURITY_EVENTS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "2592000000",  # 30 days
                "compression.type": "gzip",
            }
        },

        # Resource topics
        KafkaTopic.RESOURCE_EVENTS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },

        # Notification topics
        KafkaTopic.NOTIFICATION_EVENTS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },

        # System topics
        KafkaTopic.SYSTEM_EVENTS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },

        # Saga topics
        KafkaTopic.SAGA_EVENTS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },

        # Infrastructure topics
        KafkaTopic.DEAD_LETTER_QUEUE: {
            "num_partitions": 3,
            "replication_factor": 1,
            "config": {
                "retention.ms": "1209600000",  # 14 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.EVENT_BUS_STREAM: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "86400000",  # 1 day
                "compression.type": "gzip",
            }
        },
        KafkaTopic.WEBSOCKET_EVENTS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "86400000",  # 1 day
                "compression.type": "gzip",
            }
        },
    }
