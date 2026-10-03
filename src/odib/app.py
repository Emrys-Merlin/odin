"""Wiring: the running bot is the reaction consumer and a periodic reconcile tick, side by side.

`serve` supervises it: the bot only runs while ODIN is set up and `odib setup` is not running.
"""

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from odib.clock import Clock
from odib.config import Config, Env, WeeklyTime
from odib.engine import Account, dinner_week, reconcile
from odib.reactions import consume_reactions
from odib.signal import SignalAdmin, SignalClient
from odib.store import Store

logger = logging.getLogger(__name__)

TICK_INTERVAL = timedelta(seconds=60)
# How often `serve` checks whether ODIN is set up, or whether the setup changed.
SETUP_CHECK_INTERVAL = timedelta(seconds=30)
SETUP_HINT = "run: podman exec -it odib odib setup"
SETUP_RUNNING = "odib setup is running"
NOT_REGISTERED = "SIGNAL_NUMBER is not registered with the Signal API"
API_UNREACHABLE = "the Signal API is not reachable"

# Settings keys under which `odib setup` stores the chosen groups.
FLAT_GROUP_KEY = "flat_group_id"
DINNER_GROUP_KEY = "dinner_group_id"


class Source(StrEnum):
    """Where a group ID came from."""

    ENV = "env var"
    DB = "database"
    UNSET = "not set"


@dataclass(frozen=True)
class GroupSetting:
    id: str | None
    source: Source


@dataclass(frozen=True)
class Resolution:
    """The bot's number and its groups, with where each group ID came from."""

    number: str
    flat: GroupSetting
    dinner: GroupSetting

    @property
    def account(self) -> Account | None:
        """The account to run with; None while a group ID is missing (not set up)."""
        if self.flat.id is None or self.dinner.id is None:
            return None
        return Account(
            number=self.number, flat_group_id=self.flat.id, dinner_group_id=self.dinner.id
        )

    @property
    def missing(self) -> str:
        """Why the account is not complete, e.g. "no flat group chosen"; empty if it is."""
        roles = [
            role
            for role, group in (("flat", self.flat), ("dinner", self.dinner))
            if group.id is None
        ]
        return f"no {' and no '.join(roles)} group chosen" if roles else ""


def resolve_account(env: Env, store: Store | None) -> Resolution:
    """The bot's number and the groups it sends to.

    The one place that decides where the group IDs come from; everything else asks here.
    Each group ID: the env var if set, else the value `odib setup` stored in the database, else
    not set. Without a store (no database yet) only the env vars count.
    """

    def group(env_value: str | None, key: str) -> GroupSetting:
        if env_value is not None:
            return GroupSetting(env_value, Source.ENV)
        stored = store.get_setting(key) if store is not None else None
        if stored is not None:
            return GroupSetting(stored, Source.DB)
        return GroupSetting(None, Source.UNSET)

    return Resolution(
        number=env.signal_number,
        flat=group(env.flat_group_id, FLAT_GROUP_KEY),
        dinner=group(env.dinner_group_id, DINNER_GROUP_KEY),
    )


def readiness(env: Env, store: Store, now: datetime) -> tuple[Account | None, str]:
    """The account to run with, or None and why not. Reads only the database, no Signal."""
    if store.setup_lock_held(now):
        return None, SETUP_RUNNING
    resolution = resolve_account(env, store)
    return resolution.account, resolution.missing


async def serve(
    config: Config,
    store: Store,
    client: SignalClient,
    env: Env,
    clock: Clock,
    stop: asyncio.Event,
    check_interval: timedelta = SETUP_CHECK_INTERVAL,
    tick_interval: timedelta = TICK_INTERVAL,
    admin: SignalAdmin | None = None,
) -> None:
    """Run the bot whenever ODIN is set up, until `stop` is set.

    While it is not set up, or while `odib setup` holds the setup lock, the bot waits and checks
    again every `check_interval`. With `admin`, being set up also means that the number is
    registered with the Signal API (asked before each start; an unreachable API is waited for
    the same way). While the bot runs, the database check stops it (after the tick in progress)
    when the lock is taken or the group choice changes; then it starts over with the new state.
    So finishing `odib setup` takes effect without a restart.
    """
    stopped = asyncio.create_task(stop.wait())
    waiting_for = ""
    try:
        while not stop.is_set():
            account, reason = readiness(env, store, clock.now())
            if account is not None and admin is not None:
                reason = await _registration_problem(admin, env.signal_number)
                if reason:
                    account = None
            if account is None:
                if reason != waiting_for:
                    if reason == SETUP_RUNNING:
                        logger.info("odib setup is running; waiting until it has finished")
                    elif reason == API_UNREACHABLE:
                        logger.warning("%s; waiting until it is", API_UNREACHABLE)
                    else:
                        logger.warning("ODIN is not set up yet (%s) — %s", reason, SETUP_HINT)
                    waiting_for = reason
                await asyncio.wait({stopped}, timeout=check_interval.total_seconds())
                continue
            waiting_for = ""
            _log_sources(env, store)
            await _supervise(
                config, store, client, env, account, clock, stopped, check_interval, tick_interval
            )
    finally:
        stopped.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stopped


async def _registration_problem(admin: SignalAdmin, number: str) -> str:
    """Why `number` cannot be used with the Signal API right now; empty if it can."""
    try:
        accounts = await admin.list_accounts()
    except Exception as e:  # whatever it is, the API is not usable yet; keep waiting
        logger.debug("listing the Signal API's accounts failed: %r", e)
        return API_UNREACHABLE
    return "" if number in accounts else NOT_REGISTERED


async def _supervise(
    config: Config,
    store: Store,
    client: SignalClient,
    env: Env,
    account: Account,
    clock: Clock,
    stopped: asyncio.Task[object],
    check_interval: timedelta,
    tick_interval: timedelta,
) -> None:
    """Run the bot with `account` until shutdown or until the setup state changes."""
    bot_stop = asyncio.Event()
    bot = asyncio.create_task(
        run_bot(config, store, client, account, clock, bot_stop, tick_interval)
    )
    try:
        while not bot.done():
            await asyncio.wait(
                {bot, stopped},
                timeout=check_interval.total_seconds(),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stopped.done() or bot.done():
                break
            current, reason = readiness(env, store, clock.now())
            if current != account:
                logger.info("setup changed (%s); pausing the bot", reason or "new groups")
                break
    finally:
        bot_stop.set()
        await bot  # finishes the tick in progress; re-raises a failure of the bot


def _log_sources(env: Env, store: Store) -> None:
    resolution = resolve_account(env, store)
    for role, group in (("flat", resolution.flat), ("dinner", resolution.dinner)):
        logger.info("%s group %s (from %s)", role, group.id, group.source)


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
