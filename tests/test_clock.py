import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from odib.clock import FixedClock


def test_fixed_clock_stands_still_until_moved() -> None:
    start = datetime(2026, 10, 6, 16, 0, tzinfo=UTC)
    clock = FixedClock(start)
    assert clock.now() == clock.now() == start
    clock.set(start + timedelta(days=1))
    assert clock.now() == start + timedelta(days=1)


def test_fixed_clock_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="naive"):
        FixedClock(datetime(2026, 10, 6, 16, 0))


def test_fixed_clock_sleep_advances_the_time() -> None:
    start = datetime(2026, 10, 6, 16, 0, tzinfo=UTC)
    clock = FixedClock(start)
    asyncio.run(clock.sleep(timedelta(seconds=60)))
    assert clock.now() == start + timedelta(seconds=60)
