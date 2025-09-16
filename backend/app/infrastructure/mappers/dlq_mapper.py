from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Mapping

from confluent_kafka import Message

from app.dlq.models import (
    DLQBatchRetryResult,
    DLQFields,
    DLQMessage,
    DLQMessageFilter,
    DLQMessageStatus,
    DLQMessageUpdate,
    DLQRetryResult,
)
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events import BaseEvent


class DLQMapper:
    """Mongo/Kafka ↔ DLQMessage conversions."""

    @staticmethod
    def to_mongo_document(message: DLQMessage) -> dict[str, object]:
        doc: dict[str, object] = {
            DLQFields.EVENT: message.event.to_dict(),
            DLQFields.ORIGINAL_TOPIC: message.original_topic,
            DLQFields.ERROR: message.error,
            DLQFields.RETRY_COUNT: message.retry_count,
            DLQFields.FAILED_AT: message.failed_at,
            DLQFields.STATUS: message.status,
            DLQFields.PRODUCER_ID: message.producer_id,
        }
        if message.event_id:
            doc[DLQFields.EVENT_ID] = message.event_id
        if message.created_at:
            doc[DLQFields.CREATED_AT] = message.created_at
        if message.last_updated:
            doc[DLQFields.LAST_UPDATED] = message.last_updated
        if message.next_retry_at:
            doc[DLQFields.NEXT_RETRY_AT] = message.next_retry_at
        if message.retried_at:
            doc[DLQFields.RETRIED_AT] = message.retried_at
        if message.discarded_at:
            doc[DLQFields.DISCARDED_AT] = message.discarded_at
        if message.discard_reason:
            doc[DLQFields.DISCARD_REASON] = message.discard_reason
        if message.dlq_offset is not None:
            doc[DLQFields.DLQ_OFFSET] = message.dlq_offset
        if message.dlq_partition is not None:
            doc[DLQFields.DLQ_PARTITION] = message.dlq_partition
        if message.last_error:
            doc[DLQFields.LAST_ERROR] = message.last_error
        return doc

    @staticmethod
    def from_mongo_document(data: Mapping[str, object]) -> DLQMessage:
        schema_registry = SchemaRegistryManager()

        def parse_dt(value: object) -> datetime | None:
            if value is None:
                return None
            if isinstance(value, datetime):
                return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            if isinstance(value, str):
                return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
            raise ValueError("Invalid datetime type")

        failed_at_raw = data.get(DLQFields.FAILED_AT)
        if failed_at_raw is None:
            raise ValueError("Missing failed_at")
        failed_at = parse_dt(failed_at_raw)
        if failed_at is None:
            raise ValueError("Invalid failed_at value")

        event_data = data.get(DLQFields.EVENT)
        if not isinstance(event_data, dict):
            raise ValueError("Missing or invalid event data")
        event = schema_registry.deserialize_json(event_data)

        status_raw = data.get(DLQFields.STATUS, DLQMessageStatus.PENDING)
        status = DLQMessageStatus(str(status_raw))

        retry_count_value: int = data.get(DLQFields.RETRY_COUNT, 0)  # type: ignore[assignment]
        dlq_offset_value: int | None = data.get(DLQFields.DLQ_OFFSET)  # type: ignore[assignment]
        dlq_partition_value: int | None = data.get(DLQFields.DLQ_PARTITION)  # type: ignore[assignment]

        return DLQMessage(
            event=event,
            original_topic=str(data.get(DLQFields.ORIGINAL_TOPIC, "")),
            error=str(data.get(DLQFields.ERROR, "")),
            retry_count=retry_count_value,
            failed_at=failed_at,
            status=status,
            producer_id=str(data.get(DLQFields.PRODUCER_ID, "unknown")),
            event_id=str(data.get(DLQFields.EVENT_ID, "") or event.event_id),
            created_at=parse_dt(data.get(DLQFields.CREATED_AT)),
            last_updated=parse_dt(data.get(DLQFields.LAST_UPDATED)),
            next_retry_at=parse_dt(data.get(DLQFields.NEXT_RETRY_AT)),
            retried_at=parse_dt(data.get(DLQFields.RETRIED_AT)),
            discarded_at=parse_dt(data.get(DLQFields.DISCARDED_AT)),
            discard_reason=str(data.get(DLQFields.DISCARD_REASON, "")) or None,
            dlq_offset=dlq_offset_value,
            dlq_partition=dlq_partition_value,
            last_error=str(data.get(DLQFields.LAST_ERROR, "")) or None,
        )

    @staticmethod
    def from_kafka_message(message: Message, schema_registry: SchemaRegistryManager) -> DLQMessage:
        record_value = message.value()
        if record_value is None:
            raise ValueError("Message has no value")

        data = json.loads(record_value.decode("utf-8"))
        event_data = data.get("event", {})
        event = schema_registry.deserialize_json(event_data)

        headers: dict[str, str] = {}
        msg_headers = message.headers()
        if msg_headers:
            for key, value in msg_headers:
                headers[key] = value.decode("utf-8") if value else ""

        failed_at_str = data.get("failed_at")
        failed_at = (
            datetime.fromisoformat(failed_at_str).replace(tzinfo=timezone.utc)
            if failed_at_str
            else datetime.now(timezone.utc)
        )

        offset: int = message.offset()  # type: ignore[assignment]
        partition: int = message.partition()  # type: ignore[assignment]

        return DLQMessage(
            event=event,
            original_topic=data.get("original_topic", "unknown"),
            error=data.get("error", "Unknown error"),
            retry_count=data.get("retry_count", 0),
            failed_at=failed_at,
            status=DLQMessageStatus.PENDING,
            producer_id=data.get("producer_id", "unknown"),
            event_id=event.event_id,
            headers=headers,
            dlq_offset=offset if offset >= 0 else None,
            dlq_partition=partition if partition >= 0 else None,
        )

    @staticmethod
    def to_response_dict(message: DLQMessage) -> dict[str, object]:
        return {
            "event_id": message.event_id,
            "event_type": message.event_type,
            "event": message.event.to_dict(),
            "original_topic": message.original_topic,
            "error": message.error,
            "retry_count": message.retry_count,
            "failed_at": message.failed_at,
            "status": message.status,
            "age_seconds": message.age_seconds,
            "producer_id": message.producer_id,
            "dlq_offset": message.dlq_offset,
            "dlq_partition": message.dlq_partition,
            "last_error": message.last_error,
            "next_retry_at": message.next_retry_at,
            "retried_at": message.retried_at,
            "discarded_at": message.discarded_at,
            "discard_reason": message.discard_reason,
        }

    @staticmethod
    def retry_result_to_dict(result: DLQRetryResult) -> dict[str, object]:
        d: dict[str, object] = {"event_id": result.event_id, "status": result.status}
        if result.error:
            d["error"] = result.error
        return d

    @staticmethod
    def batch_retry_result_to_dict(result: DLQBatchRetryResult) -> dict[str, object]:
        return {
            "total": result.total,
            "successful": result.successful,
            "failed": result.failed,
            "details": [DLQMapper.retry_result_to_dict(d) for d in result.details],
        }

    # Domain construction and updates
    @staticmethod
    def from_failed_event(
            event: BaseEvent,
            original_topic: str,
            error: str,
            producer_id: str,
            retry_count: int = 0,
    ) -> DLQMessage:
        return DLQMessage(
            event=event,
            original_topic=original_topic,
            error=error,
            retry_count=retry_count,
            failed_at=datetime.now(timezone.utc),
            status=DLQMessageStatus.PENDING,
            producer_id=producer_id,
        )

    @staticmethod
    def update_to_mongo(update: DLQMessageUpdate) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        doc: dict[str, object] = {
            str(DLQFields.STATUS): update.status,
            str(DLQFields.LAST_UPDATED): now,
        }
        if update.next_retry_at is not None:
            doc[str(DLQFields.NEXT_RETRY_AT)] = update.next_retry_at
        if update.retried_at is not None:
            doc[str(DLQFields.RETRIED_AT)] = update.retried_at
        if update.discarded_at is not None:
            doc[str(DLQFields.DISCARDED_AT)] = update.discarded_at
        if update.retry_count is not None:
            doc[str(DLQFields.RETRY_COUNT)] = update.retry_count
        if update.discard_reason is not None:
            doc[str(DLQFields.DISCARD_REASON)] = update.discard_reason
        if update.last_error is not None:
            doc[str(DLQFields.LAST_ERROR)] = update.last_error
        if update.extra:
            doc.update(update.extra)
        return doc

    @staticmethod
    def filter_to_query(f: DLQMessageFilter) -> dict[str, object]:
        query: dict[str, object] = {}
        if f.status:
            query[DLQFields.STATUS] = f.status
        if f.topic:
            query[DLQFields.ORIGINAL_TOPIC] = f.topic
        if f.event_type:
            query[DLQFields.EVENT_TYPE] = f.event_type
        return query
