"""Wiring: the running bot is the reaction consumer and a periodic reconcile tick, side by side."""

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from odib.clock import Clock
from odib.config import Config, Env, WeeklyTime
from odib.engine import Account, dinner_week, reconcile
from odib.reactions import consume_reactions
from odib.signal import SignalClient
from odib.store import Store

logger = logging.getLogger(__name__)

TICK_INTERVAL = timedelta(seconds=60)


def resolve_account(env: Env) -> Account:
    """The bot's number and the groups it sends to.

    The one place that decides where the group IDs come from; everything else asks here.
    """
    return Account(
        number=env.signal_number,
        flat_group_id=env.flat_group_id,
        dinner_group_id=env.dinner_group_id,
    )


async def run_bot(
    config: Config,
    store: Store,
    client: SignalClient,
    account: Account,
    clock: Clock,
    stop: asyncio.Event,
    tick_interval: timedelta = TICK_INTERVAL,
) -> None:
    """Consume reactions and reconcile every `tick_interval` until `stop` is set.

    The first tick runs right away. A tick in progress is finished before shutting down, so a
    sent message is always recorded. If the event stream ends or fails, the bot stops with an
    error: a container restart is the simplest way back to a working connection.
    """
    consumer = asyncio.create_task(consume_reactions(client, store, config, clock))
    stopped = asyncio.create_task(stop.wait())
    try:
        while True:
            await _tick(config, store, client, account, clock)
            done, _ = await asyncio.wait(
                {consumer, stopped},
                timeout=tick_interval.total_seconds(),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stopped in done:
                logger.info("shutting down")
                return
            if consumer in done:
                consumer.result()  # re-raises a failure
                raise RuntimeError("the Signal event stream ended")
    finally:
        for task in (consumer, stopped):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def _tick(
    config: Config, store: Store, client: SignalClient, account: Account, clock: Clock
) -> None:
    try:
        await reconcile(config, store, client, account, clock.now())
    except Exception:
        logger.exception("reconcile tick failed; retrying next tick")


@dataclass(frozen=True)
class Upcoming:
    """A scheduled action and when it happens next."""

    name: str
    at: datetime
    note: str = ""


def upcoming_actions(config: Config, now: datetime) -> list[Upcoming]:
    """The next occurrence of each scheduled action at or after `now`, in time order.

    Schedule only: whether an action is actually sent depends on the state at that time.
    """
    s = config.schedule
    points: list[tuple[str, WeeklyTime, str]] = [
        ("flat ask", s.flat_ask, "flat group"),
    ]
    if s.nudge is not None:
        points.append(("nudge", s.nudge, "flat group, only if nobody confirmed"))
    points += [
        ("announcement / cancellation", s.flat_deadline, "dinner group"),
        ("tally", s.tally, "flat group, only if dinner is on"),
    ]
    week = dinner_week(config, now)
    upcoming = []
    for name, point, note in points:
        at = config.when(point, week)
        if at < now:
            at = config.when(point, week + timedelta(weeks=1))
        upcoming.append(Upcoming(name, at, note))
    return sorted(upcoming, key=lambda u: u.at.astimezone(UTC))
