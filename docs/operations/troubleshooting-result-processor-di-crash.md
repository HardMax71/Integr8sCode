# Result Processor DI Container Crash - Debugging Session

## The Problem That Ate My Afternoon

So you're here because executions are timing out with "Execution timed out waiting for a final status" and you have no idea why. Been there. Let me save you some time.

## What Was Actually Happening

The result-processor service was crash-looping on startup. Every. Single. Time. 

The error message was buried in the logs:
```
dishka.exceptions.GraphMissingFactoryError: Cannot find factory for (RateLimitMetrics, component='')
```

Which, if you're like me, made you go "what the hell does the result processor need rate limiting for?"

## The Real Issue

Turns out it's a classic dependency injection nightmare. Here's the chain of doom:

1. Result-processor needs to mark events as already processed (idempotency)
2. So it needs `IdempotencyManager`
3. Which needs `RedisIdempotencyRepository` 
4. Which needs a Redis client
5. Which comes from `RedisProvider`
6. But `RedisProvider` ALSO provides `RateLimitService` (because why not)
7. And `RateLimitService` needs `RateLimitMetrics`
8. Which lives in `ConnectionProvider`
9. Which wasn't included in the result-processor's container config 🤦

## How the Execution Pipeline Actually Works

Let me break this down because it took me forever to piece together:

```
User clicks "Run" → Execution created (status: queued)
                  ↓
    ExecutionRequestedEvent → Kafka
                  ↓
         Coordinator picks it up
                  ↓
        Saga orchestrator runs
                  ↓
     K8s-worker creates the pod
                  ↓
    Pod runs the Python script
                  ↓
        Pod completes/fails
                  ↓
    Pod-monitor sees the change
                  ↓
   ExecutionCompletedEvent → Kafka
                  ↓
   Result-processor consumes it  ← THIS WAS BROKEN
                  ↓
    Updates MongoDB (status: completed)
                  ↓
        SSE notifies frontend
```

When result-processor is dead, events just pile up in Kafka and executions stay "queued" forever.

## The Fix

In `app/core/container.py`, the result-processor container was missing providers:

**Before (broken):**
```python
def create_result_processor_container() -> AsyncContainer:
    return make_async_container(
        SettingsProvider(),
        DatabaseProvider(),
        EventProvider(),
        MessagingProvider(),
        ResultProcessorProvider(),
    )
```

**After (working):**
```python
def create_result_processor_container() -> AsyncContainer:
    return make_async_container(
        SettingsProvider(),
        DatabaseProvider(),
        CoreServicesProvider(),    # Added - provides tracing stuff
        ConnectionProvider(),      # Added - THIS IS THE KEY ONE (has RateLimitMetrics)
        RedisProvider(),          # Added - provides Redis client
        EventProvider(),
        MessagingProvider(),
        ResultProcessorProvider(),
    )
```

## How to Debug This in the Future

### 1. Check if all workers are actually running:
```bash
docker ps | grep -E "coordinator|k8s-worker|pod-monitor|result-processor|saga-orchestrator"
```

If any are missing or restarting, that's your problem.

### 2. Check the logs of the crashing service:
```bash
docker logs result-processor --tail 100
```

Look for `GraphMissingFactoryError` - that means DI container issues.

### 3. Check if events are flowing:
```bash
# See if pod completed
kubectl get pods -n integr8scode | grep <execution-id>

# Check if pod-monitor saw it
docker logs pod-monitor | grep <execution-id>

# Check if completion event was published
docker logs pod-monitor | grep "execution_completed.*<execution-id>"

# Check if result-processor consumed it
docker logs result-processor | grep <execution-id>
```

### 4. Check MongoDB directly:
```bash
docker exec backend python -c "
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from app.settings import get_settings

async def check():
    settings = get_settings()
    db_name = settings.MONGODB_URL.split('/')[-1].split('?')[0]
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[db_name]
    
    exec = await db.executions.find_one({'execution_id': '<YOUR-EXECUTION-ID>'})
    if exec:
        print(f\"Status: {exec.get('status')}\")
        print(f\"Updated: {exec.get('updated_at')}\")

asyncio.run(check())
"
```

## Lessons Learned

1. **DI containers are tricky** - They only validate dependencies at runtime, not build time
2. **Transitive dependencies matter** - Just because you don't directly use RateLimitMetrics doesn't mean you don't need its provider
3. **Workers need minimal containers** - Don't just copy the main app container config
4. **Volume mounts save time** - The fact that `./backend:/app:ro` was mounted meant fixes applied immediately without rebuilding

## Why This Keeps Happening

The Dishka DI system is powerful but unforgiving. When you add a new dependency to a provider that's used by workers, you need to check EVERY worker's container configuration. 

The worst part? The error message tells you what's missing but not WHY it's needed. You have to trace through the entire dependency graph to figure out the chain.

## Prevention

1. **Add integration tests** that actually run all workers and verify end-to-end flow
2. **Document worker dependencies** explicitly in each worker's Dockerfile
3. **Consider dependency groups** - maybe create a `WorkerCoreProviders` that all workers use
4. **Better health checks** - workers should expose health endpoints that the orchestrator can monitor

## TL;DR

If executions are timing out, check if result-processor is running. If it's not, it's probably missing a provider in its DI container config. Add the missing providers to `create_result_processor_container()` and restart.

And remember: when in doubt, grep the logs. The answer is always in there... somewhere.