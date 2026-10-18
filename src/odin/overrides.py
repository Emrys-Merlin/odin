"""Config overrides: values changed via chat, stored in the state DB on top of the TOML config.

The TOML file stays the read-only default; an override replaces one value of it until it is
reset. Overrides are applied to the parsed `Config` and validated exactly like the TOML, so the
effective config is always a valid one. Keys and values are strings:

- ``templates.<name>`` — the template text, for the weekly templates in `EDITABLE_TEMPLATES`.
- ``schedule.<point>`` — ``"<weekday> <HH:MM>"`` (e.g. ``"wed 18:00"``), for `SCHEDULE_POINTS`.
- ``schedule.nudge.enabled`` — ``"true"`` or ``"false"``.
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
from odin.engine import Transition, record_transition, transition
from odin.store import Override, Store

logger = logging.getLogger(__name__)

# The weekly templates that can be edited via chat (not `hello` / `flat_test`).
EDITABLE_TEMPLATES = ("flat_ask", "nudge", "announcement", "cancellation", "tally")
# The schedule points that can be moved via chat, in schedule order.
SCHEDULE_POINTS = ("flat_ask", "nudge", "flat_deadline", "rsvp_by", "tally", "cook", "dinner")

NUDGE_ENABLED_KEY = "schedule.nudge.enabled"
_BOOLS = {"true": True, "false": False}


def template_key(name: str) -> str:
    """The override key for template `name`, e.g. ``templates.flat_ask``."""
    if name not in EDITABLE_TEMPLATES:
        raise ValueError(f"not an editable template: {name!r}")
    return f"templates.{name}"


def schedule_key(point: str) -> str:
    """The override key for schedule point `point`, e.g. ``schedule.flat_deadline``."""
    if point not in SCHEDULE_POINTS:
        raise ValueError(f"not a schedule point: {point!r}")
    return f"schedule.{point}"


def format_weekly_time(point: WeeklyTime) -> str:
    """A schedule override value, e.g. ``"wed 18:00"``."""
    return str(point)


def format_bool(value: bool) -> str:
    """A `NUDGE_ENABLED_KEY` value."""
    return "true" if value else "false"


TEMPLATE_KEYS = {template_key(name): name for name in EDITABLE_TEMPLATES}
SCHEDULE_KEYS = {schedule_key(point): point for point in SCHEDULE_POINTS}
# Every valid override key that `apply_overrides` takes.
KEYS = frozenset({*TEMPLATE_KEYS, *SCHEDULE_KEYS, NUDGE_ENABLED_KEY})
DINNER_KEY = schedule_key("dinner")
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
    for key, value in overrides.items():
        if key in TEMPLATE_KEYS:
            name = TEMPLATE_KEYS[key]
            if not value.strip():
                raise ConfigError(f"{key}: empty message text")
            templates[name] = Template.parse(value.strip(), TEMPLATE_PLACEHOLDERS[name], key)
        elif key in SCHEDULE_KEYS:
            point = SCHEDULE_KEYS[key]
            schedule["nudge_time" if point == "nudge" else point] = _parse_weekly_time(value, key)
        elif key == NUDGE_ENABLED_KEY:
            if value not in _BOOLS:
                raise ConfigError(f'{key}: must be "true" or "false", got {value!r}')
            schedule["nudge_enabled"] = _BOOLS[value]
        else:
            raise ConfigError(f"unknown override {key!r}")
    if not (templates or schedule):
        return base
    new_schedule = dataclasses.replace(base.schedule, **schedule)
    _check_order(new_schedule)
    return dataclasses.replace(
        base,
        schedule=new_schedule,
        templates=dataclasses.replace(base.templates, **templates),
    )


@dataclass(frozen=True)
class PendingDinner:
    """A new dinner weekday waiting for the running dinner week to end."""

    point: WeeklyTime  # the new dinner time
    after_week: date  # the running week when it was set
    switch: datetime  # when it takes effect: the dinner of `after_week`
    transition: Transition  # the first dinner week under it, and a week dropped on the way
    changed_by: str
    changed_at: datetime


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
    """
    return _resolve(base, store, now)[0]


def pending_dinner(base: Config, store: Store, now: datetime) -> PendingDinner | None:
    """The dinner weekday change waiting at `now`, if there is one (see `effective_config`)."""
    return _resolve(base, store, now)[1]


def _resolve(base: Config, store: Store, now: datetime) -> tuple[Config, PendingDinner | None]:
    stored = store.overrides()
    pending = stored.pop(PENDING_DINNER_KEY, None)
    config, valid = _apply_valid(base, store, stored)
    if pending is None:
        return config, None
    try:
        if pending.after_week is None:
            raise ConfigError("no dinner week to wait for")
        new = apply_overrides(base, valid | {DINNER_KEY: pending.value})
        # ValueError if `after_week` is no dinner week of `config`; or if a week would straddle.
        switch = config.when(config.schedule.dinner, pending.after_week)
        weeks = transition(new, switch)
    except ValueError as e:
        _drop(store, pending, e)
        return config, None
    if now < switch:
        return config, PendingDinner(
            point=new.schedule.dinner,
            after_week=pending.after_week,
            switch=switch,
            transition=weeks,
            changed_by=pending.changed_by,
            changed_at=pending.changed_at,
        )
    with store.transaction():
        store.delete_override(PENDING_DINNER_KEY)
        if pending.value == format_weekly_time(base.schedule.dinner):
            store.delete_override(DINNER_KEY)  # back to the config file's value
        else:
            store.set_override(DINNER_KEY, pending.value, pending.changed_by, pending.changed_at)
        record_transition(store, weeks)
    logger.info("dinner is now on %s, from the week of %s", pending.value, weeks.first_week)
    return new, None


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
