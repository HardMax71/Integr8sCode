import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
import redis.asyncio as redis
from app.core.database_context import Database
from app.domain.enums.user import UserRole
from app.schemas_pydantic.execution import ExecutionRequest, ExecutionResponse
from app.schemas_pydantic.saved_script import SavedScriptCreateRequest
from app.schemas_pydantic.user import UserCreate
from httpx import AsyncClient

from tests.helpers.cleanup import cleanup_db_and_redis


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(db: Database, redis_client: redis.Redis) -> AsyncGenerator[None, None]:
    """Clean DB and Redis before each E2E test."""
    await cleanup_db_and_redis(db, redis_client)
    yield


# --- Request fixtures ---


@pytest.fixture
def simple_execution_request() -> ExecutionRequest:
    """Simple python print execution."""
    return ExecutionRequest(script="print('test')", lang="python", lang_version="3.11")


@pytest.fixture
def long_running_execution_request() -> ExecutionRequest:
    """30 second sleep execution."""
    return ExecutionRequest(
        script="import time; time.sleep(30); print('done')",
        lang="python",
        lang_version="3.11",
    )


@pytest.fixture
def error_execution_request() -> ExecutionRequest:
    """Execution that raises an error."""
    return ExecutionRequest(
        script="raise ValueError('test error')",
        lang="python",
        lang_version="3.11",
    )


@pytest.fixture
def new_user_request() -> UserCreate:
    """Unique user registration request."""
    uid = uuid.uuid4().hex[:8]
    return UserCreate(
        username=f"user_{uid}",
        email=f"user_{uid}@test.com",
        password="SecurePass123!",
        role=UserRole.USER,
    )


@pytest.fixture
def new_admin_request() -> UserCreate:
    """Unique admin registration request."""
    uid = uuid.uuid4().hex[:8]
    return UserCreate(
        username=f"admin_{uid}",
        email=f"admin_{uid}@test.com",
        password="SecurePass123!",
        role=UserRole.ADMIN,
    )


@pytest.fixture
def new_script_request() -> SavedScriptCreateRequest:
    """Unique saved script request."""
    uid = uuid.uuid4().hex[:8]
    return SavedScriptCreateRequest(
        name=f"Script {uid}",
        script="print('hello')",
        lang="python",
        lang_version="3.11",
    )


# --- Created resource fixtures ---


@pytest.fixture
async def created_execution(
    test_user: AsyncClient, simple_execution_request: ExecutionRequest
) -> ExecutionResponse:
    """Execution created by test_user."""
    resp = await test_user.post(
        "/api/v1/execute", json=simple_execution_request.model_dump()
    )
    assert resp.status_code == 200
    return ExecutionResponse.model_validate(resp.json())


@pytest.fixture
async def created_execution_admin(
    test_admin: AsyncClient, simple_execution_request: ExecutionRequest
) -> ExecutionResponse:
    """Execution created by test_admin."""
    resp = await test_admin.post(
        "/api/v1/execute", json=simple_execution_request.model_dump()
    )
    assert resp.status_code == 200
    return ExecutionResponse.model_validate(resp.json())
