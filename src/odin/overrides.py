"""Config overrides: values changed via chat, stored in the state DB on top of the TOML config.

The TOML file stays the read-only default; an override replaces one value of it until it is
reset. Overrides are applied to the parsed `Config` and validated exactly like the TOML, so the
effective config is always a valid one. Keys and values are strings:

- ``templates.<name>`` — the template text, for the weekly templates in `EDITABLE_TEMPLATES`.
- ``schedule.<point>`` — ``"<weekday> <HH:MM>"`` (e.g. ``"wed 18:00"``), for `SCHEDULE_POINTS`.
- ``schedule.nudge.enabled`` — ``"true"`` or ``"false"``.

The bot computes `effective_config` on every tick and every handled event, so a change made via
chat takes effect without a restart.
"""

import dataclasses
import logging
from collections.abc import Mapping

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
from odin.store import Store

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
# Every valid override key.
KEYS = frozenset({*TEMPLATE_KEYS, *SCHEDULE_KEYS, NUDGE_ENABLED_KEY})


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


def effective_config(base: Config, store: Store) -> Config:
    """The TOML config `base` with the stored overrides applied.

    Overrides that no longer validate (e.g. the TOML changed underneath, so they now break the
    schedule order) are deleted from the store with a warning instead of crashing the bot. They
    are tried oldest first, so of two that conflict the more recent change is dropped.
    """
    stored = store.overrides()
    values = {key: override.value for key, override in stored.items()}
    try:
        return apply_overrides(base, values)
    except ConfigError:
        pass
    valid: dict[str, str] = {}
    for key, value in values.items():  # oldest change first
        try:
            apply_overrides(base, valid | {key: value})
        except ConfigError as e:
            logger.warning(
                "dropping config override %s = %r (by %s): %s",
                key,
                value,
                stored[key].changed_by,
                e,
            )
            store.delete_override(key)
        else:
            valid[key] = value
    return apply_overrides(base, valid)
