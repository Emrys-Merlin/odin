"""Config overrides: values changed via chat, stored in the state DB on top of the TOML config.

The TOML file stays the read-only default; an override replaces one value of it until it is
reset. Overrides are applied to the parsed `Config` and validated exactly like the TOML, so the
effective config is always a valid one. Keys and values are strings:

- ``templates.<name>`` — the template text, for the weekly templates in `EDITABLE_TEMPLATES`.
- ``schedule.<point>`` — ``"<weekday> <HH:MM>"`` (e.g. ``"wed 18:00"``), for each `SchedulePoint`.
- ``schedule.nudge.enabled`` — ``"true"`` or ``"false"``.
- ``decision.cancellation.enabled`` — ``"true"`` or ``"false"``: whether the dinner group gets the
  cancellation when dinner does not take place (see `odin.config.Decision`).
- ``schedule.dinner.next`` (`PENDING_DINNER_KEY`) — a new dinner time on another weekday, as for
  ``schedule.dinner``, that waits for the running dinner week to end. Its `Override.after_week`
  is that week; once its dinner starts, the value becomes the ``schedule.dinner`` override, and a
  week dropped by the switch is recorded in the store (`odin.engine.record_transition`), so the
  engine posts its cancellation. Dinner weeks are named by their dinner date, so a new weekday
  must never take over in the middle of a week (see `odin.engine.transition`).

The bot computes `effective_config` on every tick and every handled event, so a change made via
chat takes effect without a restart.
"""

import dataclasses
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

from odin.config import (
    TEMPLATE_PLACEHOLDERS,
    Config,
    ConfigError,
    Template,
    WeeklyTime,
    _check_order,
    _parse_time,
    _parse_weekday,
)
from odin.cycle import SchedulePoint, TemplateName
from odin.engine import Transition, dinner_week, record_transition, transition
from odin.store import AppliedDinner, Override, Store

logger = logging.getLogger(__name__)

# The weekly templates that can be edited via chat (not `hello` / `flat_test`).
EDITABLE_TEMPLATES = tuple(name for name in TemplateName if name.editable)

NUDGE_ENABLED_KEY = "schedule.nudge.enabled"
CANCELLATION_ENABLED_KEY = "decision.cancellation.enabled"
_BOOLS = {"true": True, "false": False}


def template_key(name: TemplateName) -> str:
    """The override key for template `name`, e.g. ``templates.flat_ask``."""
    if not name.editable:
        raise ValueError(f"not an editable template: {name!r}")
    return f"templates.{name}"


def schedule_key(point: SchedulePoint) -> str:
    """The override key for schedule point `point`, e.g. ``schedule.flat_deadline``."""
    return f"schedule.{point}"


def format_weekly_time(point: WeeklyTime) -> str:
    """A schedule override value, e.g. ``"wed 18:00"``."""
    return str(point)


def format_bool(value: bool) -> str:
    """A `NUDGE_ENABLED_KEY` or `CANCELLATION_ENABLED_KEY` value."""
    return "true" if value else "false"


TEMPLATE_KEYS = {template_key(name): name for name in EDITABLE_TEMPLATES}
SCHEDULE_KEYS = {schedule_key(point): point for point in SchedulePoint}
# Every valid override key that `apply_overrides` takes.
KEYS = frozenset({*TEMPLATE_KEYS, *SCHEDULE_KEYS, NUDGE_ENABLED_KEY, CANCELLATION_ENABLED_KEY})
DINNER_KEY = schedule_key(SchedulePoint.DINNER)
PENDING_DINNER_KEY = "schedule.dinner.next"


def _parse_weekly_time(value: str, where: str) -> WeeklyTime:
    parts = value.split()
    if len(parts) != 2:
        raise ConfigError(f'{where}: expected "<weekday> <HH:MM>", got {value!r}')
    weekday, time = parts
    return WeeklyTime(_parse_weekday(weekday, where), _parse_time(time, where))


def apply_overrides(base: Config, overrides: Mapping[str, str]) -> Config:
    """`base` with `overrides` applied. Raises ConfigError on an unknown key or invalid value.

    Validated like the TOML: templates against their allowed placeholders, times and weekdays
    with the same parsers, and the order of the resulting schedule.
    """
    templates: dict[str, Template] = {}
    schedule: dict[str, object] = {}
    decision: dict[str, object] = {}
    for key, value in overrides.items():
        if key in TEMPLATE_KEYS:
            name = TEMPLATE_KEYS[key]
            if not value.strip():
                raise ConfigError(f"{key}: empty message text")
            templates[name] = Template.parse(value.strip(), TEMPLATE_PLACEHOLDERS[name], key)
        elif key in SCHEDULE_KEYS:
            schedule[SCHEDULE_KEYS[key].attr] = _parse_weekly_time(value, key)
        elif key == NUDGE_ENABLED_KEY:
            schedule["nudge_enabled"] = _parse_bool(key, value)
        elif key == CANCELLATION_ENABLED_KEY:
            decision["cancellation"] = _parse_bool(key, value)
        else:
            raise ConfigError(f"unknown override {key!r}")
    if not (templates or schedule or decision):
        return base
    new_schedule = dataclasses.replace(base.schedule, **schedule)
    _check_order(new_schedule)
    return dataclasses.replace(
        base,
        schedule=new_schedule,
        templates=dataclasses.replace(base.templates, **templates),
        decision=dataclasses.replace(base.decision, **decision),
    )


def _parse_bool(key: str, value: str) -> bool:
    if value not in _BOOLS:
        raise ConfigError(f'{key}: must be "true" or "false", got {value!r}')
    return _BOOLS[value]


@dataclass(frozen=True)
class PendingDinner:
    """A new dinner weekday waiting for the running dinner week to end."""

    point: WeeklyTime  # the new dinner time
    after_week: date  # the running week when it was set
    switch: datetime  # when it takes effect: the dinner of `after_week`
    transition: Transition  # the first dinner week under it, and a week dropped on the way
    # Who set it via chat, and when; both None for a change made in the config file.
    changed_by: str | None = None
    changed_at: datetime | None = None

    @property
    def from_config(self) -> bool:
        """Whether the change comes from the config file rather than from the chat."""
        return self.changed_by is None


def current_values(store: Store) -> dict[str, str]:
    """The stored overrides that `apply_overrides` takes: all but a pending dinner weekday."""
    return {
        key: override.value
        for key, override in store.overrides().items()
        if key != PENDING_DINNER_KEY
    }


def effective_config(base: Config, store: Store, now: datetime) -> Config:
    """The TOML config `base` with the overrides stored and in effect at `now` applied.

    The one place that decides the effective config. Overrides that no longer validate (e.g. the
    TOML changed underneath, so they now break the schedule order) are deleted from the store with
    a warning instead of crashing the bot. They are tried oldest first, so of two that conflict
    the more recent change is dropped.

    A pending dinner weekday (`PENDING_DINNER_KEY`) is applied from the dinner of its
    `after_week` on; the first call at or after that moment stores it as the ``schedule.dinner``
    override and, in the same transaction, records a week the switch drops (with the scheduled
    switch, not the time of the call, so a late first call still counts the grace from it). It is
    dropped with a warning if it no longer fits (its week is no dinner week under the current
    config, or the schedule with it is out of order).

    **A new dinner weekday in the config file** waits the same way. The store remembers the dinner
    the weeks run on (`Store.applied_dinner`). When the TOML with the overrides in effect names
    another weekday, that is detected here:

    - If the running dinner week (the one whose dinner is next under the applied dinner) has
      started — its flat ask is due, anything of it is recorded, or a pending chat change waits
      for it; the same rule as for a chat change (`/settime dinner`) — the weeks keep
      the applied dinner until that week's dinner starts. The week is stored as held, so the
      decision survives restarts. At the switch the new weekday takes over like a pending chat
      change: `odin.engine.transition` at the scheduled dinner and `record_transition`, in the
      same transaction as storing the new applied dinner.
    - Else (between weeks: after dinner and before the next flat ask) it applies at once, with
      `record_transition` at `now`.
    - A pending chat change wins over the config file, as every override does: at the switch it
      becomes the ``schedule.dinner`` override, which hides the config file's dinner.
    - If the schedule is out of order with the applied dinner, the new weekday applies at once.
    """
    return _resolve(base, store, now)[0]


def pending_dinner(base: Config, store: Store, now: datetime) -> PendingDinner | None:
    """The dinner weekday change waiting at `now`, if there is one (see `effective_config`).

    A pending chat change is returned rather than a waiting change from the config file: it wins.
    """
    return _resolve(base, store, now)[1]


def config_dinner_change(base: Config, store: Store) -> tuple[WeeklyTime, WeeklyTime] | None:
    """The applied dinner and the config file's dinner, if the config file moved dinner to another
    weekday that has not taken over yet. Only reads the store (for `odin check-config`)."""
    applied = store.applied_dinner()
    if applied is None:
        return None
    try:
        target = apply_overrides(base, current_values(store)).schedule.dinner
        point = _parse_weekly_time(applied.point, "applied dinner")
    except ConfigError:
        return None
    return None if point.weekday == target.weekday else (point, target)


def _resolve(base: Config, store: Store, now: datetime) -> tuple[Config, PendingDinner | None]:
    """The effective config at `now` and the dinner weekday change waiting then; does what
    `effective_config` describes, one step per function below."""
    stored = store.overrides()
    pending = stored.pop(PENDING_DINNER_KEY, None)
    target, valid = _apply_valid(base, store, stored)
    applied = _applied_dinner(store, target, now)
    point = _parse_weekly_time(applied.point, "applied dinner")

    # A new weekday from the config file: decide whether it waits for the running week.
    config, held = _resolve_config_dinner(store, target, now, applied, point, pending)

    # A pending chat change, on top of what the dinner weeks run on now.
    config, waiting, switched = _resolve_pending(base, store, now, config, valid, pending)
    if switched or held is None:
        return config, waiting
    return _resolve_held(store, target, now, config, waiting, held, point)


def _resolve_config_dinner(
    store: Store,
    target: Config,
    now: datetime,
    applied: AppliedDinner,
    point: WeeklyTime,
    pending: Override | None,
) -> tuple[Config, date | None]:
    """The config the dinner weeks run on now, and the week the config file's new dinner weekday
    waits for (None if none waits). `target` is the effective config, `point` the applied dinner.
    """
    if point.weekday == target.schedule.dinner.weekday:
        _keep_weekday(store, target, applied)
        return target, None
    running = _with_dinner(target, point)
    if running is None:
        logger.error(
            "the config file moves dinner from %s to %s, but its schedule is out of order "
            "with dinner on %s; the new weekday applies at once",
            point,
            target.schedule.dinner,
            point,
        )
        _switch_config(store, target, now, point)
        return target, None
    if applied.held_week is not None:
        return running, applied.held_week
    return _hold_or_switch(store, target, now, applied, running, pending)


def _keep_weekday(store: Store, target: Config, applied: AppliedDinner) -> None:
    """The config file's dinner is on the applied weekday: store its time, and drop a held week."""
    if applied.held_week is not None:
        logger.warning(
            "the config file's dinner (%s) is back on the weekday the dinner weeks run on; "
            "the waiting change of the dinner weekday is gone",
            target.schedule.dinner,
        )
    current = AppliedDinner(format_weekly_time(target.schedule.dinner))
    if applied != current:
        store.set_applied_dinner(current.point)


def _hold_or_switch(
    store: Store,
    target: Config,
    now: datetime,
    applied: AppliedDinner,
    running: Config,
    pending: Override | None,
) -> tuple[Config, date | None]:
    """A new dinner weekday from the config file, just detected: hold the running dinner week if
    it has started (and return it), else switch at once. `running` keeps the applied dinner."""
    point = running.schedule.dinner
    week = dinner_week(running, now)
    if not _week_started(store, running, now, week, pending):
        _switch_config(store, target, now, point)
        return target, None
    store.set_applied_dinner(applied.point, week)
    logger.warning(
        "the config file moves dinner from %s to %s; the running dinner week of %s "
        "keeps %s, the new weekday takes over at its dinner (%s)",
        point,
        target.schedule.dinner,
        week,
        point,
        running.when(point, week),
    )
    return running, week


def _week_started(
    store: Store, running: Config, now: datetime, week: date, pending: Override | None
) -> bool:
    """Whether dinner week `week` has started: its flat ask is due, anything of it is recorded, or
    a pending chat change waits for it."""
    return (
        store.has_any_action(week)
        or running.when(running.schedule.flat_ask, week) <= now
        or (pending is not None and pending.after_week == week)
    )


def _resolve_held(
    store: Store,
    target: Config,
    now: datetime,
    config: Config,
    waiting: PendingDinner | None,
    held: date,
    point: WeeklyTime,
) -> tuple[Config, PendingDinner | None]:
    """The config file's new weekday waits for week `held`: switch once its dinner has started,
    else return it as the waiting change (unless a chat change `waiting` wins)."""
    try:
        switch = config.when(config.schedule.dinner, held)
    except ValueError:  # cannot happen: `held` is a dinner week of the applied dinner
        switch = now
    if now >= switch:
        _switch_config(store, target, switch, point)
        return target, None
    if waiting is not None:
        return config, waiting  # the chat change wins: it is what takes over at the switch
    try:
        weeks = transition(target, switch)
    except ValueError:  # cannot happen: the switch is a dinner of an in-order schedule
        weeks = Transition(switch, dinner_week(target, switch), None)
    return config, PendingDinner(
        point=target.schedule.dinner, after_week=held, switch=switch, transition=weeks
    )


def _applied_dinner(store: Store, target: Config, now: datetime) -> AppliedDinner:
    """The dinner the weeks run on; stored on first use.

    For a database from before it was stored: the effective dinner `target`, unless the latest
    week with records is on another weekday and its dinner is still to come. Then the config file
    changed the weekday in the middle of that week, and the week keeps its weekday (at `target`'s
    time, since the old one is not known).
    """
    applied = store.applied_dinner()
    if applied is not None:
        return applied
    point = target.schedule.dinner
    latest = store.latest_week_before(date.max)
    if latest is not None and latest.weekday() != point.weekday:
        guess = WeeklyTime(latest.weekday(), point.time)
        running = _with_dinner(target, guess)
        if running is not None and running.when(guess, latest) > now:
            logger.warning(
                "the dinner week of %s was started on another weekday than the config file's "
                "dinner (%s); assuming dinner on %s for it",
                latest,
                point,
                guess,
            )
            point = guess
    applied = AppliedDinner(format_weekly_time(point))
    store.set_applied_dinner(applied.point)
    return applied


def _with_dinner(config: Config, point: WeeklyTime) -> Config | None:
    """`config` with dinner at `point`; None if its schedule is out of order with it."""
    schedule = dataclasses.replace(config.schedule, dinner=point)
    try:
        _check_order(schedule)
    except ConfigError:
        return None
    return dataclasses.replace(config, schedule=schedule)


def _switch_config(store: Store, target: Config, switch: datetime, old: WeeklyTime) -> None:
    """Let the config file's new dinner weekday take over at `switch` (see `effective_config`)."""
    try:
        weeks: Transition | None = transition(target, switch)
    except ValueError:
        # Only when it applies at once although the new weekday's week has begun: nothing is
        # recorded for the running week, so the new week runs like one the bot was down for
        # (late steps caught up within their windows), and no week is dropped.
        weeks = None
    with store.transaction():
        store.set_applied_dinner(format_weekly_time(target.schedule.dinner))
        if weeks is not None:
            record_transition(store, weeks)
    first = dinner_week(target, switch) if weeks is None else weeks.first_week
    dropped = None if weeks is None else weeks.dropped_week
    logger.warning(
        "dinner moves from %s to %s as the config file says, from the dinner week of %s on%s",
        old,
        target.schedule.dinner,
        first,
        "" if dropped is None else f"; the week of {dropped} is dropped (cancellation only)",
    )


def _resolve_pending(
    base: Config,
    store: Store,
    now: datetime,
    config: Config,
    valid: Mapping[str, str],
    pending: Override | None,
) -> tuple[Config, PendingDinner | None, bool]:
    """Apply a pending chat change of the dinner weekday on top of `config`, the config the weeks
    run on now. Returns the effective config, the change if it still waits, and whether it took
    over just now."""
    if pending is None:
        return config, None, False
    try:
        if pending.after_week is None:
            raise ConfigError("no dinner week to wait for")
        new = apply_overrides(base, {**valid, DINNER_KEY: pending.value})
        # ValueError if `after_week` is no dinner week of `config`; or if a week would straddle.
        switch = config.when(config.schedule.dinner, pending.after_week)
        weeks = transition(new, switch)
    except ValueError as e:
        _drop(store, pending, e)
        return config, None, False
    if now < switch:
        waiting = PendingDinner(
            point=new.schedule.dinner,
            after_week=pending.after_week,
            switch=switch,
            transition=weeks,
            changed_by=pending.changed_by,
            changed_at=pending.changed_at,
        )
        return config, waiting, False
    with store.transaction():
        store.delete_override(PENDING_DINNER_KEY)
        if pending.value == format_weekly_time(base.schedule.dinner):
            store.delete_override(DINNER_KEY)  # back to the config file's value
        else:
            store.set_override(DINNER_KEY, pending.value, pending.changed_by, pending.changed_at)
        record_transition(store, weeks)
        store.set_applied_dinner(format_weekly_time(new.schedule.dinner))
    logger.info("dinner is now on %s, from the week of %s", pending.value, weeks.first_week)
    return new, None, True


def _apply_valid(
    base: Config, store: Store, stored: Mapping[str, Override]
) -> tuple[Config, dict[str, str]]:
    """`base` with the valid ones of `stored` applied, and those; the others are deleted."""
    values = {key: override.value for key, override in stored.items()}
    try:
        return apply_overrides(base, values), values
    except ConfigError:
        pass
    valid: dict[str, str] = {}
    for key, value in values.items():  # oldest change first
        try:
            apply_overrides(base, valid | {key: value})
        except ConfigError as e:
            _drop(store, stored[key], e)
        else:
            valid[key] = value
    return apply_overrides(base, valid), valid


def _drop(store: Store, override: Override, error: Exception) -> None:
    logger.warning(
        "dropping config override %s = %r (by %s): %s",
        override.key,
        override.value,
        override.changed_by,
        error,
    )
    store.delete_override(override.key)
