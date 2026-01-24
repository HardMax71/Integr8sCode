import json
from datetime import datetime, timedelta, timezone

import pytest
import redis.asyncio as redis
from app.domain.idempotency import IdempotencyRecord, IdempotencyStatus
from app.services.idempotency.redis_repository import (
    RedisIdempotencyRepository,
    _iso,
    _json_default,
    _parse_iso_datetime,
)
from pymongo.errors import DuplicateKeyError

pytestmark = [pytest.mark.e2e, pytest.mark.redis]


class TestHelperFunctions:
    def test_iso_datetime(self) -> None:
        dt = datetime(2025, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
        result = _iso(dt)
        assert result == "2025-01-15T10:30:45+00:00"

    def test_iso_datetime_with_timezone(self) -> None:
        dt = datetime(2025, 1, 15, 10, 30, 45, tzinfo=timezone(timedelta(hours=5)))
        result = _iso(dt)
        assert result == "2025-01-15T05:30:45+00:00"

    def test_json_default_datetime(self) -> None:
        dt = datetime(2025, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
        result = _json_default(dt)
        assert result == "2025-01-15T10:30:45+00:00"

    def test_json_default_other(self) -> None:
        obj = {"key": "value"}
        result = _json_default(obj)
        assert result == "{'key': 'value'}"

    def test_parse_iso_datetime_variants(self) -> None:
        result1 = _parse_iso_datetime("2025-01-15T10:30:45+00:00")
        assert result1 is not None and result1.year == 2025
        result2 = _parse_iso_datetime("2025-01-15T10:30:45Z")
        assert result2 is not None and result2.tzinfo == timezone.utc
        assert _parse_iso_datetime(None) is None
        assert _parse_iso_datetime("") is None
        assert _parse_iso_datetime("not-a-date") is None


@pytest.fixture
def repository(redis_client: redis.Redis) -> RedisIdempotencyRepository:
    return RedisIdempotencyRepository(redis_client, key_prefix="idempotency")


@pytest.fixture
def sample_record() -> IdempotencyRecord:
    return IdempotencyRecord(
        key="test-key",
        status=IdempotencyStatus.PROCESSING,
        event_type="test.event",
        event_id="event-123",
        created_at=datetime(2025, 1, 15, 10, 30, 45, tzinfo=timezone.utc),
        ttl_seconds=5,
        completed_at=None,
        processing_duration_ms=None,
        error=None,
        result_json=None,
    )


def test_full_key_helpers(repository: RedisIdempotencyRepository) -> None:
    assert repository._full_key("my") == "idempotency:my"
    assert repository._full_key("idempotency:my") == "idempotency:my"


def test_doc_record_roundtrip(repository: RedisIdempotencyRepository) -> None:
    rec = IdempotencyRecord(
        key="k",
        status=IdempotencyStatus.COMPLETED,
        event_type="e.t",
        event_id="e-1",
        created_at=datetime(2025, 1, 15, tzinfo=timezone.utc),
        ttl_seconds=60,
        completed_at=datetime(2025, 1, 15, 0, 1, tzinfo=timezone.utc),
        processing_duration_ms=123,
        error="err",
        result_json='{"ok":true}',
    )
    doc = repository._record_to_doc(rec)
    back = repository._doc_to_record(doc)
    assert back.key == rec.key and back.status == rec.status


@pytest.mark.asyncio
async def test_insert_find_update_delete_flow(
    repository: RedisIdempotencyRepository,
    redis_client: redis.Redis,
    sample_record: IdempotencyRecord,
) -> None:
    # Insert processing (NX)
    await repository.insert_processing(sample_record)
    key = repository._full_key(sample_record.key)
    ttl = await redis_client.ttl(key)
    assert ttl == sample_record.ttl_seconds or ttl > 0

    # Duplicate insert should raise DuplicateKeyError
    with pytest.raises(DuplicateKeyError):
        await repository.insert_processing(sample_record)

    # Find returns the record
    found = await repository.find_by_key(sample_record.key)
    assert found is not None and found.key == sample_record.key

    # Update preserves TTL when present
    sample_record.status = IdempotencyStatus.COMPLETED
    sample_record.completed_at = datetime.now(timezone.utc)
    sample_record.processing_duration_ms = 10
    sample_record.result_json = json.dumps({"result": True})
    updated = await repository.update_record(sample_record)
    assert updated == 1
    ttl_after = await redis_client.ttl(key)
    assert ttl_after == ttl or ttl_after <= ttl  # ttl should not increase

    # Delete
    deleted = await repository.delete_key(sample_record.key)
    assert deleted == 1
    assert await repository.find_by_key(sample_record.key) is None


@pytest.mark.asyncio
async def test_update_record_when_missing(
    repository: RedisIdempotencyRepository, sample_record: IdempotencyRecord
) -> None:
    # If key missing, update returns 0
    res = await repository.update_record(sample_record)
    assert res == 0


@pytest.mark.asyncio
async def test_aggregate_status_counts(
    repository: RedisIdempotencyRepository, redis_client: redis.Redis
) -> None:
    # Seed few keys directly using repository
    statuses = (IdempotencyStatus.PROCESSING, IdempotencyStatus.PROCESSING, IdempotencyStatus.COMPLETED)
    for i, status in enumerate(statuses):
        rec = IdempotencyRecord(
            key=f"k{i}",
            status=status,
            event_type="t",
            event_id=f"e{i}",
            created_at=datetime.now(timezone.utc),
            ttl_seconds=60,
        )
        await repository.insert_processing(rec)
        if status != IdempotencyStatus.PROCESSING:
            rec.status = status
            rec.completed_at = datetime.now(timezone.utc)
            await repository.update_record(rec)

    counts = await repository.aggregate_status_counts("idempotency")
    assert counts[IdempotencyStatus.PROCESSING] == 2
    assert counts[IdempotencyStatus.COMPLETED] == 1


@pytest.mark.asyncio
async def test_health_check(repository: RedisIdempotencyRepository) -> None:
    await repository.health_check()  # should not raise
