Lifecycle of Long‑Running Services

We used to manage service lifecycles (start/stop) in a very ad‑hoc way. Some services started themselves, others were started by DI providers, some runners remembered to stop things, some didn’t. A few places tried to “clean up” with locals() checks and best‑effort branching. It worked until it didn’t: shutdowns were inconsistent, readiness was unclear, and tricky bugs hid in error paths.

We briefly considered a destructor‑style approach (start in __init__, stop in __del__). That idea looks simple on paper, but it’s the wrong fit for asyncio. You can’t await from a destructor, and destructors may run after the event loop is already gone. That prevents clean cancellation and flush of background tasks and network clients. It also swallows errors. In short, it’s unreliable.

The pattern that actually fits Python and asyncio is the language’s own RAII: async context managers. Each service implements start/stop, and also implements __aenter__/__aexit__ that call start/stop. Runners and the FastAPI lifespan manage the lifetime of multiple services with an AsyncExitStack so the code stays flat and readable. Startup is deterministic, and shutdown always happens while the loop is still alive.

What changed

• Services with long‑running background work now implement the async context manager protocol. Coordinator, KubernetesWorker, PodMonitor, SSE Kafka→Redis bridge, EventStoreConsumer, ResultProcessor, DLQManager, EventBus, and the Kafka producer all expose __aenter__/__aexit__ that call start/stop.

• DI providers return unstarted instances for these services. The FastAPI lifespan acquires them and uses an AsyncExitStack to start/stop them in a single place. That removed scattered start/stop logic from providers and made shutdown order explicit.

• Worker entrypoints (coordinator, k8s‑worker, pod‑monitor, event‑replay, result‑processor, dlq‑processor) use AsyncExitStack as well. No more “if 'x' in locals()” cleanups or nested with statements. Each runner acquires the services it needs, enters them in the stack, and blocks. When it’s time to exit, everything stops in reverse order.

Why this is better

It’s deterministic: stop() runs while the loop is alive, in the right order. It’s explicit without being noisy: lifecycle sits in one place (lifespan or runner) instead of being sprinkled everywhere. It avoids Python destructors and other hidden magic. It also makes tests a lot less flaky: you can spin up a service in an async with block and know it always gets torn down.

How to build new services

Keep it simple: implement async start() and stop(). If your service owns a background task, start it in start() and cancel/await it in stop(). Add __aenter__/__aexit__ that await start/stop. Don’t start in __init__, and don’t rely on __del__. Callers will manage lifetime with an async with or an AsyncExitStack.

How to use many services together

Use an AsyncExitStack at the call site:

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(producer)
        await stack.enter_async_context(coordinator)
        # add more services as needed
        await asyncio.Event().wait()

The stack starts services in the order they’re added and stops them in reverse. That’s usually what we want: consumers stop before producers flush, monitors stop before their publishers, etc.

Trade‑offs

We gave up the “invisible” start‑in‑constructor convenience in return for correctness and clarity. The payoff is fewer shutdown bugs, fewer hidden dependencies, and far less boilerplate. The code is simpler to read and reason about because the lifetime of each component is explicit and managed by the language tools built for it.

