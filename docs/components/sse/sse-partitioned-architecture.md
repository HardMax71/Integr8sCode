# SSE architecture notes

The SSE system uses Redis pub/sub to route events from producers to connected browser clients. Events are published to
Redis channels keyed by execution ID (`sse:exec:{id}`), and the SSE service subscribes to these channels to stream
events to the browser.

## How it works

Events flow from producers (API, Pod Monitor, Result Processor) through Redis pub/sub to the SSE service. The SSE
service manages client connections and streams events as they arrive. Each execution gets its own Redis channel, so
events are naturally scoped to the right client.

## Scaling

The architecture scales horizontally because Redis pub/sub handles fan-out across multiple backend instances. Multiple
backend instances can handle SSE connections behind a load balancer — each instance subscribes to the relevant Redis
channels for its connected clients.

## Key files

| File                                                                                                              | Purpose             |
|-------------------------------------------------------------------------------------------------------------------|---------------------|
| [`sse_service.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/services/sse/sse_service.py)   | Client connections  |
| [`redis_bus.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/services/sse/redis_bus.py)       | Redis pub/sub       |
