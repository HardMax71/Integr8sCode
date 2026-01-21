"""Minimal fake Kafka clients for DI container testing."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeAIOKafkaProducer:
    """Minimal fake for AIOKafkaProducer - satisfies DI container."""

    bootstrap_servers: str = "localhost:9092"
    sent_messages: list[tuple[str, bytes, list[tuple[str, bytes]]]] = field(default_factory=list)
    _started: bool = False

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def send_and_wait(
        self,
        topic: str,
        value: bytes,
        headers: list[tuple[str, bytes]] | None = None,
        **kwargs: Any,
    ) -> None:
        self.sent_messages.append((topic, value, headers or []))

    async def __aenter__(self) -> "FakeAIOKafkaProducer":
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()


@dataclass
class FakeAIOKafkaConsumer:
    """Minimal fake for AIOKafkaConsumer - satisfies DI container."""

    bootstrap_servers: str = "localhost:9092"
    group_id: str = "test-group"
    _topics: list[str] = field(default_factory=list)
    _started: bool = False
    _messages: list[Any] = field(default_factory=list)

    def subscribe(self, topics: list[str]) -> None:
        self._topics = topics

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def commit(self) -> None:
        pass

    def assignment(self) -> set[Any]:
        return set()

    async def seek_to_beginning(self, *partitions: Any) -> None:
        pass

    async def seek_to_end(self, *partitions: Any) -> None:
        pass

    def seek(self, partition: Any, offset: int) -> None:
        pass

    def __aiter__(self) -> "FakeAIOKafkaConsumer":
        return self

    async def __anext__(self) -> Any:
        if self._messages:
            return self._messages.pop(0)
        raise StopAsyncIteration
