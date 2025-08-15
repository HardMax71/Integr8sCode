import json
from enum import IntEnum

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from app.core.logging import logger
from app.core.service_dependencies import WebSocketRepositoryDep
from app.schemas_pydantic.websocket import WebSocketErrorCode
from app.websocket.connection_manager import WebSocketConnection


class WebSocketState(IntEnum):
    """WebSocket connection states based on the WebSocket protocol."""
    CONNECTING = 0
    CONNECTED = 1
    CLOSING = 2
    CLOSED = 3


router = APIRouter()


@router.websocket("/ws/executions")
async def websocket_endpoint(
        websocket: WebSocket,
        repository: WebSocketRepositoryDep,
        token: str | None = Query(None),
        client_id: str | None = Query(None),
) -> None:
    """WebSocket endpoint for execution updates.
    
    Args:
        websocket: WebSocket connection
        token: Authentication token
        client_id: Optional client ID
        repository: WebSocket repository
    """
    connection: WebSocketConnection | None = None

    try:
        # Authenticate connection
        try:
            user_info = await repository.authenticate_connection(websocket, token)
        except Exception as e:
            logger.error(f"WebSocket authentication failed: {e}")
            # Only close the WebSocket if it's still open
            if websocket.client_state.value <= WebSocketState.CONNECTED:
                await websocket.close(code=4001, reason="Authentication failed")
            return

        # Create connection
        connection = await repository.create_connection(
            websocket=websocket,
            client_id=client_id,
            user_id=user_info.user_id
        )

        # Send authentication success
        await repository.send_auth_success(connection, user_info.user_id)

        # Message processing loop
        while True:
            try:
                message = await websocket.receive_json()
            except json.JSONDecodeError:
                await repository.send_error(
                    connection,
                    "Invalid JSON",
                    WebSocketErrorCode.INVALID_JSON
                )
                continue

            # Process message
            await repository.process_message(
                connection=connection,
                message=message,
                user_info=user_info.model_dump()
            )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {connection.client_id if connection else 'unknown'}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        if connection:
            await repository.disconnect_client(connection.client_id)


@router.get("/ws/demo")
async def websocket_demo() -> HTMLResponse:
    """WebSocket demo page.
    
    Returns:
        HTML demo page
    """
    return HTMLResponse(content=get_demo_html())


def get_demo_html() -> str:
    """Get WebSocket demo HTML content.
    
    Returns:
        HTML content for demo page
    """
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WebSocket Demo</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            #messages { border: 1px solid #ccc; height: 300px; overflow-y: auto; padding: 10px; margin: 10px 0; }
            .message { margin: 5px 0; padding: 5px; border-radius: 3px; }
            .sent { background: #e3f2fd; }
            .received { background: #f5f5f5; }
            .error { background: #ffebee; color: #c62828; }
            .connected { color: #2e7d32; }
            .disconnected { color: #c62828; }
            input, button { margin: 5px; padding: 5px; }
            #status { font-weight: bold; }
        </style>
    </head>
    <body>
        <h1>WebSocket Execution Updates Demo</h1>
        
        <div>
            Status: <span id="status" class="disconnected">Disconnected</span>
        </div>
        
        <div>
            <input type="text" id="token" placeholder="Auth token" size="50">
            <button onclick="connect()">Connect</button>
            <button onclick="disconnect()">Disconnect</button>
        </div>
        
        <div>
            <input type="text" id="executionId" placeholder="Execution ID" size="40">
            <button onclick="subscribe()">Subscribe</button>
            <button onclick="unsubscribe()">Unsubscribe</button>
        </div>
        
        <div>
            <button onclick="ping()">Ping</button>
            <button onclick="listSubscriptions()">List Subscriptions</button>
            <button onclick="clearMessages()">Clear</button>
        </div>
        
        <div id="messages"></div>
        
        <script>
            let ws = null;
            let clientId = 'demo-' + Math.random().toString(36).substr(2, 9);
            
            function addMessage(message, type = 'received') {
                const messages = document.getElementById('messages');
                const msgDiv = document.createElement('div');
                msgDiv.className = 'message ' + type;
                msgDiv.textContent = new Date().toLocaleTimeString() + ' - ' + message;
                messages.appendChild(msgDiv);
                messages.scrollTop = messages.scrollHeight;
            }
            
            function updateStatus(connected) {
                const status = document.getElementById('status');
                if (connected) {
                    status.textContent = 'Connected';
                    status.className = 'connected';
                } else {
                    status.textContent = 'Disconnected';
                    status.className = 'disconnected';
                }
            }
            
            function connect() {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    addMessage('Already connected', 'error');
                    return;
                }
                
                const token = document.getElementById('token').value;
                if (!token) {
                    addMessage('Please enter an authentication token', 'error');
                    return;
                }
                
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                const host = window.location.host;
                const encodedToken = encodeURIComponent(token);
                const url = `${protocol}//${host}/api/v1/ws/executions?token=${encodedToken}&client_id=${clientId}`;
                
                addMessage('Connecting...', 'sent');
                ws = new WebSocket(url);
                
                ws.onopen = function() {
                    addMessage('Connected!', 'received');
                    updateStatus(true);
                };
                
                ws.onmessage = function(event) {
                    addMessage('Received: ' + event.data, 'received');
                };
                
                ws.onerror = function(error) {
                    addMessage('Error: ' + error, 'error');
                };
                
                ws.onclose = function(event) {
                    addMessage(`Disconnected (code: ${event.code}, reason: ${event.reason})`, 'error');
                    updateStatus(false);
                };
            }
            
            function disconnect() {
                if (ws) {
                    ws.close();
                    ws = null;
                }
            }
            
            function send(message) {
                if (!ws || ws.readyState !== WebSocket.OPEN) {
                    addMessage('Not connected', 'error');
                    return;
                }
                
                const json = JSON.stringify(message);
                addMessage('Sent: ' + json, 'sent');
                ws.send(json);
            }
            
            function subscribe() {
                const executionId = document.getElementById('executionId').value;
                if (!executionId) {
                    addMessage('Please enter an execution ID', 'error');
                    return;
                }
                send({ type: 'subscribe', execution_id: executionId });
            }
            
            function unsubscribe() {
                const executionId = document.getElementById('executionId').value;
                if (!executionId) {
                    addMessage('Please enter an execution ID', 'error');
                    return;
                }
                send({ type: 'unsubscribe', execution_id: executionId });
            }
            
            function ping() {
                send({ type: 'ping' });
            }
            
            function listSubscriptions() {
                send({ type: 'list_subscriptions' });
            }
            
            function clearMessages() {
                document.getElementById('messages').innerHTML = '';
            }
        </script>
    </body>
    </html>
    """
