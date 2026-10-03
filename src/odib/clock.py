"""The clock interface. Code never calls ``datetime.now()`` directly, so tests can time travel."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The current time, timezone-aware."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """A clock that stands still until a test moves it."""

    def __init__(self, moment: datetime) -> None:
        self.set(moment)

    def now(self) -> datetime:
        return self._now

    def set(self, moment: datetime) -> None:
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError(f"naive datetime not allowed: {moment!r}")
        self._now = moment
