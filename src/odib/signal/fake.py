"""In-memory SignalClient for tests."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from odib.signal.models import Event, Group


@dataclass(frozen=True, slots=True)
class SentMessage:
    group_id: str
    text: str
    timestamp: int


class FakeSignalClient:
    """Records sent messages and yields events that tests inject.

    Sent messages get strictly increasing timestamps starting at ``first_timestamp``.
    ``events()`` yields injected events in order and ends once ``close()`` is called and
    all earlier events are consumed.
    """

    def __init__(
        self,
        number: str = "+490000000000",
        groups: list[Group] | None = None,
        first_timestamp: int = 1_000,
    ) -> None:
        self.number = number
        self.groups = list(groups or [])
        self.sent: list[SentMessage] = []
        self._next_timestamp = first_timestamp
        self._queue: asyncio.Queue[Event | None] = asyncio.Queue()

    async def send_group_message(self, group_id: str, text: str) -> int:
        timestamp = self._next_timestamp
        self._next_timestamp += 1
        self.sent.append(SentMessage(group_id=group_id, text=text, timestamp=timestamp))
        return timestamp

    async def list_groups(self) -> list[Group]:
        return list(self.groups)

    async def events(self) -> AsyncIterator[Event]:
        while (event := await self._queue.get()) is not None:
            yield event

    def inject(self, event: Event) -> None:
        self._queue.put_nowait(event)

    def close(self) -> None:
        self._queue.put_nowait(None)
