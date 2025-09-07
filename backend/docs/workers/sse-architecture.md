# Server-Sent Events (SSE) Architecture

## What is SSE and Why We Use It

Server-Sent Events is our real-time communication channel between the backend and frontend. Think of it as a one-way street where the server can push updates to the browser whenever something interesting happens. Unlike WebSockets (which we removed), SSE is simpler, more reliable, and perfect for our use case where we only need server-to-client communication.

## How SSE Works in Our Application

### The Big Picture

When a user runs code in the browser, here's what happens behind the scenes:

1. **User submits code** → Frontend makes a POST request to create an execution
2. **Backend queues the execution** → Returns an execution ID immediately  
3. **Frontend opens SSE connection** → Subscribes to `/api/v1/events/executions/{executionId}`
4. **Backend processes execution** → Kubernetes creates a pod, runs the code
5. **Events flow through Kafka** → Each state change becomes an event
6. **SSE streams events to browser** → Real-time updates appear in the UI

### The Event Flow

```
User Code → API → Kafka → Kubernetes Pod → Kafka Events → SSE → Browser
```

Every major state change in the execution lifecycle generates an event:
- `execution.requested` - Code submitted
- `execution.validated` - Input validated
- `execution.queued` - Added to processing queue
- `pod.created` - Kubernetes pod created
- `pod.running` - Container started
- `execution.completed` - Code finished successfully
- `execution.failed` - Something went wrong

## Key Components

### SSE Service (`app/services/sse/sse_service.py`)

This is the heart of our SSE implementation. It manages connections, subscribes to Kafka events, and streams them to clients. The service handles:
- Connection lifecycle management
- Event filtering based on execution ID
- Graceful shutdown with connection draining
- Automatic heartbeats to keep connections alive

### Partitioned Event Router (`app/services/sse/partitioned_event_router.py`)

This clever component distributes events across multiple Kafka partitions for better performance. It ensures that all events for a single execution stay on the same partition (maintaining order) while spreading different executions across partitions for parallelism.

### Event Buffer (`app/services/sse/event_buffer.py`)

A local buffer that temporarily stores events before streaming them to clients. This helps handle burst traffic and ensures we don't lose events if a client temporarily disconnects. The buffer:
- Stores up to 1000 events per execution
- Auto-expires after 5 minutes of inactivity
- Provides replay capability for reconnecting clients

### SSE Shutdown Manager (`app/services/sse/sse_shutdown_manager.py`)

During deployments or restarts, we need to gracefully close SSE connections. This manager:
- Tracks all active connections
- Sends shutdown notifications to clients
- Waits for clients to reconnect to a new instance
- Ensures no events are lost during the transition

## How Events Get to the Browser

Here's the journey of an event from creation to display:

1. **Event Creation**: When something happens (like a pod starting), the relevant service publishes an event to Kafka
   ```python
   await producer.send_event(
       topic="execution-events",
       event_type="pod.running",
       execution_id=execution_id,
       payload={"status": "running"}
   )
   ```

2. **Kafka Processing**: The event lands in a Kafka topic, partitioned by execution ID

3. **SSE Consumer**: Our SSE service has a Kafka consumer that subscribes to execution events
   ```python
   async for message in consumer:
       event = parse_event(message)
       await route_to_subscribers(event)
   ```

4. **Event Routing**: The SSE service checks which clients are subscribed to this execution
   ```python
   subscribers = self.execution_subscribers.get(execution_id, set())
   for client_queue in subscribers:
       await client_queue.put(event)
   ```

5. **Streaming to Client**: Each client connection has its own async generator that yields events
   ```python
   async def event_generator(execution_id):
       queue = asyncio.Queue()
       try:
           while True:
               event = await queue.get()
               yield f"data: {json.dumps(event)}\n\n"
       finally:
           cleanup_subscription()
   ```

6. **Browser Reception**: The frontend's EventSource receives and processes the event
   ```javascript
   const eventSource = new EventSource(`/api/v1/events/executions/${executionId}`);
   eventSource.onmessage = (event) => {
       const data = JSON.parse(event.data);
       updateExecutionStatus(data);
   };
   ```

## Error Handling and Resilience

### Automatic Reconnection
Browsers automatically reconnect SSE connections if they drop. Our backend handles this gracefully:
- Maintains event buffers for recent executions
- Replays missed events on reconnection
- Uses event IDs to prevent duplicates

### Heartbeats
Every 30 seconds, we send a heartbeat comment to keep the connection alive:
```
: heartbeat
```
This prevents proxies and load balancers from timing out idle connections.

### Circuit Breaking
If Kafka becomes unavailable, we:
- Return cached execution status if available
- Gracefully degrade to polling mode
- Log errors for monitoring

## Performance Optimizations

### Connection Pooling
We limit concurrent SSE connections per user to prevent resource exhaustion:
- Max 10 connections per user
- Oldest connections closed when limit reached
- Admin users get higher limits

### Event Filtering
Events are filtered at multiple levels to reduce unnecessary data transfer:
1. Kafka consumer only subscribes to relevant topics
2. SSE service filters by execution ID
3. Client can specify event types of interest

### Compression
SSE streams are compressed using gzip when supported by the client, reducing bandwidth usage by ~70%.

## Monitoring and Metrics

We track several key metrics:
- `sse.connections.active` - Current number of SSE connections
- `sse.messages.sent.total` - Total events streamed
- `sse.connection.duration` - How long connections stay open
- `event.buffer.size` - Current buffer sizes
- `kafka.consumer.lag` - How far behind we are in processing

## Security Considerations

### Authentication
Every SSE connection requires authentication:
- JWT token passed as query parameter
- Token validated before establishing connection
- Connection closed immediately if token expires

### Authorization
Users can only subscribe to their own executions:
- Execution ownership verified on subscription
- Admin users can subscribe to any execution
- Attempts to subscribe to unauthorized executions are logged

### Rate Limiting
SSE connections are rate-limited to prevent abuse:
- Max 100 connections per minute per user
- Exponential backoff for repeated connection attempts
- IP-based limiting for additional protection

## Common Issues and Troubleshooting

### "Connection keeps dropping"
- Check if the user's JWT token is expiring
- Verify proxy/load balancer timeout settings
- Look for network issues or firewall rules

### "Events arrive delayed"
- Check Kafka consumer lag metrics
- Verify event buffer isn't full
- Look for slow database queries in event processing

### "Missing events"
- Check if events are being published to Kafka
- Verify Kafka topics exist and are accessible
- Look for errors in SSE consumer logs

## Why Not WebSockets?

We initially implemented WebSockets but removed them because:
1. **Overkill**: We only need server-to-client communication
2. **Complexity**: WebSockets require more complex connection management
3. **Proxy issues**: Many corporate proxies block WebSocket connections
4. **Browser support**: SSE has excellent browser support and automatic reconnection
5. **HTTP/2 friendly**: SSE works great with HTTP/2 multiplexing

SSE gives us everything we need with less complexity and better reliability.

## Future Improvements

Some ideas we're considering:
- Event replay from specific timestamp
- Subscription to multiple executions in single connection
- Custom event filtering expressions
- WebRTC data channels for even lower latency
- Server-side event aggregation for dashboard views