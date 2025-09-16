import pytest

from app.db.repositories.sse_repository import SSERepository

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_get_execution_status(db) -> None:  # type: ignore[valid-type]
    repo = SSERepository(db)
    # Insert execution
    await db.get_collection("executions").insert_one({"execution_id": "e1", "status": "running"})
    status = await repo.get_execution_status("e1")
    assert status and status.status == "running" and status.execution_id == "e1"


@pytest.mark.asyncio
async def test_get_execution_status_none(db) -> None:  # type: ignore[valid-type]
    repo = SSERepository(db)
    assert await repo.get_execution_status("missing") is None


@pytest.mark.asyncio
async def test_get_execution_events(db) -> None:  # type: ignore[valid-type]
    repo = SSERepository(db)
    await db.get_collection("events").insert_one({"aggregate_id": "e1", "timestamp": 1, "event_type": "X"})
    events = await repo.get_execution_events("e1")
    assert len(events) == 1 and events[0].aggregate_id == "e1"


@pytest.mark.asyncio
async def test_get_execution_for_user_and_plain(db) -> None:  # type: ignore[valid-type]
    repo = SSERepository(db)
    await db.get_collection("executions").insert_one({
        "execution_id": "e1",
        "user_id": "u1",
        "status": "queued",
        "resource_usage": {}
    })
    doc = await repo.get_execution_for_user("e1", "u1")
    assert doc and doc.user_id == "u1"
    await db.get_collection("executions").insert_one({
        "execution_id": "e2", 
        "status": "queued",  # Add required status field
        "resource_usage": {}
    })
    assert (await repo.get_execution("e2")) is not None


@pytest.mark.asyncio
async def test_get_execution_for_user_not_found(db) -> None:  # type: ignore[valid-type]
    repo = SSERepository(db)
    assert await repo.get_execution_for_user("e1", "uX") is None
