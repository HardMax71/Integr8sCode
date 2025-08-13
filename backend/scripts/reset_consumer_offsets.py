#!/usr/bin/env python3
"""Reset Kafka consumer group offsets"""

import asyncio
import sys

from aiokafka import AIOKafkaConsumer
from app.schemas_avro.event_schemas import EventType


async def reset_consumer_group_offsets(group_id: str, topics: list,
                                       bootstrap_servers: str = "kafka:9092") -> bool:
    """Reset consumer group offsets to latest"""
    print(f"Resetting offsets for consumer group: {group_id}")
    print(f"Topics: {topics}")

    # Create consumer
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=bootstrap_servers,
        group_id=group_id,
        auto_offset_reset="latest",
        enable_auto_commit=False
    )

    success = False
    try:
        await consumer.start()
        print("Consumer started")

        # Get topic partitions
        partitions = consumer.assignment()
        print(f"Assigned partitions: {partitions}")

        # Seek to end for all partitions
        await consumer.seek_to_end()
        print("Seeked to end of all partitions")

        # Commit the new offsets
        await consumer.commit()
        print("Committed new offsets")

        # Print current positions
        for partition in partitions:
            position = await consumer.position(partition)
            print(f"  {partition.topic}:{partition.partition} -> {position}")

        success = True
    except Exception as e:
        print(f"Error: {e}")
        success = False
    finally:
        await consumer.stop()
        print("Consumer stopped")
    
    return success


async def main() -> None:
    # Result processor consumer group
    group_id = "result_processor_group"
    topics = [
        EventType.EXECUTION_COMPLETED, EventType.EXECUTION_FAILED,
        EventType.EXECUTION_TIMEOUT,
    ]
    success = await reset_consumer_group_offsets(group_id, topics)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
