"""Helpers shared by the test modules; import them explicitly (`from helpers import local`)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from odin.config import DEFAULT_TIMEZONE

BERLIN = ZoneInfo(DEFAULT_TIMEZONE)


def local(day: int, hour: int, minute: int = 0, month: int = 10, year: int = 2026) -> datetime:
    """A moment in the default timezone; October 2026 unless `month` or `year` say otherwise."""
    return datetime(year, month, day, hour, minute, tzinfo=BERLIN)


def ms(moment: datetime) -> int:
    """`moment` as a Signal timestamp (milliseconds since the epoch)."""
    return int(moment.timestamp() * 1000)
