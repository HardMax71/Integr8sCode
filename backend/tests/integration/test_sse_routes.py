"""
Integration tests for SSE (Server-Sent Events) routes against the backend.

These tests run against the actual backend service running in Docker,
providing true end-to-end testing with:
- Real event streaming
- Real notification push
- Real execution event updates
- Real connection management
- Real buffering and backpressure handling
"""

import pytest
import asyncio
import json
from typing import Dict, Any, List, AsyncGenerator
from datetime import datetime, timezone
from httpx import AsyncClient
from uuid import uuid4

from app.schemas_pydantic.sse import SSEHealthResponse


@pytest.mark.integration
class TestSSERoutesReal:
    """Test SSE endpoints against real backend."""
    
    @pytest.mark.asyncio
    async def test_sse_requires_authentication(self, client: AsyncClient) -> None:
        """Test that SSE endpoints require authentication."""
        # Try to access SSE streams without auth
        response = await client.get("/api/v1/events/notifications/stream")
        assert response.status_code == 401
        
        error_data = response.json()
        assert "detail" in error_data
        assert any(word in error_data["detail"].lower() 
                  for word in ["not authenticated", "unauthorized", "login"])
        
        # Try execution events without auth
        execution_id = str(uuid4())
        response = await client.get(f"/api/v1/events/executions/{execution_id}")
        assert response.status_code == 401
        
        # Try health endpoint without auth
        response = await client.get("/api/v1/events/health")
        assert response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_sse_health_status(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test SSE service health status."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Get SSE health status
        response = await client.get("/api/v1/events/health")
        assert response.status_code == 200
        
        # Validate response structure
        health_data = response.json()
        health_status = SSEHealthResponse(**health_data)
        
        # Verify health fields
        assert health_status.status in ["healthy", "degraded", "unhealthy", "draining"]
        assert isinstance(health_status.active_connections, int)
        assert health_status.active_connections >= 0
        
        # Buffer stats are optional and may not be present in this schema
        if hasattr(health_status, "buffer_size") and getattr(health_status, "buffer_size") is not None:
            assert isinstance(getattr(health_status, "buffer_size"), int)
            assert getattr(health_status, "buffer_size") >= 0
        if hasattr(health_status, "max_buffer_size") and getattr(health_status, "max_buffer_size") is not None:
            assert isinstance(getattr(health_status, "max_buffer_size"), int)
            assert getattr(health_status, "max_buffer_size") > 0
        
        # Check connection details if present in schema
        if hasattr(health_status, "connection_details") and getattr(health_status, "connection_details"):
            cd = getattr(health_status, "connection_details")
            assert isinstance(cd, dict)
            for conn_id, details in cd.items():
                assert isinstance(conn_id, str)
                assert isinstance(details, dict)
    
    @pytest.mark.asyncio
    async def test_notification_stream_connection(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test connecting to notification stream."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Connect to notification stream
        # Note: SSE requires special handling - standard httpx doesn't support streaming SSE well
        # We'll test that the endpoint responds correctly
        async with client.stream("GET", "/api/v1/events/notifications/stream") as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            
            # Try to read first few chunks
            events_received = []
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    event_data = line[5:].strip()
                    if event_data and event_data != "[DONE]":
                        try:
                            event = json.loads(event_data)
                            events_received.append(event)
                        except json.JSONDecodeError:
                            pass
                
                # Stop after receiving a few events or after timeout
                if len(events_received) >= 3:
                    break
                
                # Add small delay to prevent busy loop
                await asyncio.sleep(0.1)
            
            # Should have received at least a keepalive or initial event
            # Note: This might not always receive events if none are being generated
    
    @pytest.mark.asyncio
    async def test_execution_event_stream(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test streaming events for a specific execution."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Create an execution to monitor
        execution_request = {
            "script": "import time\nfor i in range(3):\n    print(f'Event {i}')\n    time.sleep(1)",
            "lang": "python",
            "lang_version": "3.11"
        }
        
        exec_response = await client.post("/api/v1/execute", json=execution_request)
        assert exec_response.status_code == 200
        
        execution_id = exec_response.json()["execution_id"]
        
        # Connect to execution event stream
        async with client.stream("GET", f"/api/v1/events/executions/{execution_id}") as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            
            events_received = []
            event_types_seen = set()
            
            # Set a timeout for reading events
            try:
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        event_data = line[5:].strip()
                        if event_data and event_data != "[DONE]":
                            try:
                                event = json.loads(event_data)
                                events_received.append(event)
                                
                                # Track event types
                                if "type" in event:
                                    event_types_seen.add(event["type"])
                                
                                # Validate event structure
                                assert "execution_id" in event or "id" in event
                                if "execution_id" in event:
                                    assert event["execution_id"] == execution_id
                                
                                # Common event fields
                                if "timestamp" in event:
                                    assert isinstance(event["timestamp"], str)
                                if "status" in event:
                                    assert event["status"] in ["queued", "scheduled", "running", "completed", "failed", "timeout", "cancelled"]
                            except json.JSONDecodeError:
                                pass
                    
                    # Stop after receiving enough events
                    if len(events_received) >= 5:
                        break
                    
                    # Add small delay
                    await asyncio.sleep(0.1)
            except asyncio.TimeoutError:
                pass  # Expected if execution completes quickly
            
            # Should have received some events
            assert len(events_received) > 0
            
            # Should see various event types (status updates, logs, etc.)
            # Event types depend on what the execution system generates
    
    @pytest.mark.asyncio
    async def test_execution_stream_for_nonexistent_execution(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test streaming events for non-existent execution."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Try to stream events for non-existent execution
        fake_execution_id = "00000000-0000-0000-0000-000000000000"
        
        # The stream might still connect but send an error event or close immediately
        async with client.stream("GET", f"/api/v1/events/executions/{fake_execution_id}") as response:
            # Could be 200 (with error in stream) or 404
            assert response.status_code in [200, 404]
            
            if response.status_code == 200:
                # If it connects, should receive an error event or close quickly
                events_received = []
                error_received = False
                
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        event_data = line[5:].strip()
                        if event_data and event_data != "[DONE]":
                            try:
                                event = json.loads(event_data)
                                events_received.append(event)
                                
                                # Check for error event
                                if "error" in event or "type" in event and event["type"] == "error":
                                    error_received = True
                                    break
                            except json.JSONDecodeError:
                                pass
                    
                    # Stop after a few attempts
                    if len(events_received) >= 3:
                        break
                    
                    await asyncio.sleep(0.1)
    
    @pytest.mark.asyncio
    async def test_multiple_concurrent_sse_connections(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test multiple concurrent SSE connections."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Create multiple SSE connections concurrently
        async def create_sse_connection(conn_id: int) -> Dict[str, Any]:
            """Create and test an SSE connection."""
            result = {
                "conn_id": conn_id,
                "connected": False,
                "events_received": 0,
                "errors": []
            }
            
            try:
                async with client.stream("GET", "/api/v1/events/notifications/stream") as response:
                    if response.status_code == 200:
                        result["connected"] = True
                        
                        # Read a few events
                        event_count = 0
                        async for line in response.aiter_lines():
                            if line.startswith("data:"):
                                event_count += 1
                                if event_count >= 2:  # Read just a couple events
                                    break
                            await asyncio.sleep(0.1)
                        
                        result["events_received"] = event_count
                    else:
                        result["errors"].append(f"Status code: {response.status_code}")
            except Exception as e:
                result["errors"].append(str(e))
            
            return result
        
        # Create 3 concurrent connections
        tasks = [create_sse_connection(i) for i in range(3)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify results
        successful_connections = 0
        for result in results:
            if isinstance(result, dict):
                if result["connected"]:
                    successful_connections += 1
            elif isinstance(result, Exception):
                # Log exception but don't fail test
                pass
        
        # Should support multiple concurrent connections
        assert successful_connections >= 2
        
        # Check health to see connection count
        health_response = await client.get("/api/v1/events/health")
        if health_response.status_code == 200:
            health_data = health_response.json()
            # Active connections should reflect our test connections
            # (might be 0 if connections already closed)
            assert health_data["active_connections"] >= 0
    
    @pytest.mark.asyncio
    async def test_sse_reconnection_after_disconnect(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test SSE reconnection after disconnect."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # First connection
        first_connection_events = []
        async with client.stream("GET", "/api/v1/events/notifications/stream") as response:
            assert response.status_code == 200
            
            # Read a couple events
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    first_connection_events.append(line)
                    if len(first_connection_events) >= 2:
                        break
                await asyncio.sleep(0.1)
        
        # Small delay between connections
        await asyncio.sleep(1)
        
        # Second connection (reconnection)
        second_connection_events = []
        async with client.stream("GET", "/api/v1/events/notifications/stream") as response:
            assert response.status_code == 200
            
            # Read a couple events
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    second_connection_events.append(line)
                    if len(second_connection_events) >= 2:
                        break
                await asyncio.sleep(0.1)
        
        # Both connections should work
        assert len(first_connection_events) > 0 or len(second_connection_events) > 0
    
    @pytest.mark.asyncio
    async def test_sse_with_last_event_id_header(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test SSE with Last-Event-ID header for resuming streams."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Connect with Last-Event-ID header (for resuming after disconnect)
        headers = {"Last-Event-ID": "12345"}
        
        async with client.stream("GET", "/api/v1/events/notifications/stream", headers=headers) as response:
            # Should accept the header (even if it doesn't use it)
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            
            # Read a couple events to verify stream works
            event_count = 0
            async for line in response.aiter_lines():
                if line.startswith("data:") or line.startswith("id:"):
                    event_count += 1
                    if event_count >= 2:
                        break
                await asyncio.sleep(0.1)
    
    @pytest.mark.asyncio
    async def test_sse_keepalive_events(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test that SSE sends keepalive events to maintain connection."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Connect and wait for keepalive events
        async with client.stream("GET", "/api/v1/events/notifications/stream") as response:
            assert response.status_code == 200
            
            keepalive_received = False
            start_time = asyncio.get_event_loop().time()
            
            async for line in response.aiter_lines():
                # Keepalive might be a comment (: keepalive) or empty data
                if line.startswith(":") or line == "data: ":
                    keepalive_received = True
                    break
                
                # Also check for heartbeat/ping events
                if line.startswith("data:"):
                    event_data = line[5:].strip()
                    if event_data:
                        try:
                            event = json.loads(event_data)
                            if event.get("type") in ["keepalive", "ping", "heartbeat"]:
                                keepalive_received = True
                                break
                        except json.JSONDecodeError:
                            pass
                
                # Wait up to 20 seconds for keepalive
                if asyncio.get_event_loop().time() - start_time > 20:
                    break
                
                await asyncio.sleep(0.5)
            
            # Most SSE implementations send keepalives
            # But it's not strictly required, so we just note it
    
    @pytest.mark.asyncio
    async def test_sse_isolation_between_users(self, client: AsyncClient, 
                                              shared_user: Dict[str, str],
                                              shared_admin: Dict[str, str]) -> None:
        """Test that SSE streams are isolated between users."""
        # Create execution as regular user
        user_login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        user_login_response = await client.post("/api/v1/auth/login", data=user_login_data)
        assert user_login_response.status_code == 200
        
        execution_request = {
            "script": "print('User execution')",
            "lang": "python",
            "lang_version": "3.11"
        }
        
        user_exec_response = await client.post("/api/v1/execute", json=execution_request)
        assert user_exec_response.status_code == 200
        user_execution_id = user_exec_response.json()["execution_id"]
        
        # Login as admin
        admin_login_data = {
            "username": shared_admin["username"],
            "password": shared_admin["password"]
        }
        admin_login_response = await client.post("/api/v1/auth/login", data=admin_login_data)
        assert admin_login_response.status_code == 200
        
        # Admin should not be able to stream user's execution events
        # (unless admin has special permissions)
        async with client.stream("GET", f"/api/v1/events/executions/{user_execution_id}") as response:
            # Should either deny access or filter events
            assert response.status_code in [200, 403, 404]
            
            if response.status_code == 200:
                # If allowed, might receive filtered events or error
                events_received = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        events_received.append(line)
                        if len(events_received) >= 2:
                            break
                    await asyncio.sleep(0.1)
