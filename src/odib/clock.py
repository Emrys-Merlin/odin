"""The clock interface. Code never calls ``datetime.now()`` directly, so tests can time travel."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The current time, timezone-aware."""
        ...

    async def sleep(self, delay: timedelta) -> None:
        """Wait for ``delay`` (countdowns and polling in ``odib setup``)."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, delay: timedelta) -> None:
        await asyncio.sleep(delay.total_seconds())


class FixedClock:
    """A clock that stands still until a test moves it, or until someone sleeps on it."""

    def __init__(self, moment: datetime) -> None:
        self.set(moment)

    def now(self) -> datetime:
        return self._now

    def set(self, moment: datetime) -> None:
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError(f"naive datetime not allowed: {moment!r}")
        self._now = moment

    async def sleep(self, delay: timedelta) -> None:
        """Advance the time by ``delay`` at once, and let other tasks run."""
        self._now += delay
        await asyncio.sleep(0)
