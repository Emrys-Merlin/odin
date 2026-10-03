"""Settings: a TOML config file (schedule, emoji, templates) plus env vars (deployment values).

Everything is validated at load time, so a bad config fails on startup instead of on Tuesday at
18:00. All settings objects are frozen.
"""

import datetime as dt
import os
import re
import string
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(ValueError):
    """The config file or the environment is invalid."""


# --- Env ----------------------------------------------------------------------------------------

DEFAULT_SIGNAL_API_URL = "http://localhost:8080"
_E164 = re.compile(r"\+[1-9]\d{6,14}")


@dataclass(frozen=True)
class Env:
    """Deployment-specific values from environment variables."""

    signal_number: str
    flat_group_id: str
    dinner_group_id: str
    signal_api_url: str
    config_path: Path
    db_path: Path


def load_env(environ: Mapping[str, str]) -> Env:
    def required(name: str) -> str:
        value = environ.get(name, "").strip()
        if not value:
            raise ConfigError(f"environment variable {name} is not set")
        return value

    signal_number = required("SIGNAL_NUMBER")
    if not _E164.fullmatch(signal_number):
        raise ConfigError(f"SIGNAL_NUMBER must be in E.164 format (+49…), got {signal_number!r}")

    signal_api_url = environ.get("SIGNAL_API_URL", "").strip() or DEFAULT_SIGNAL_API_URL
    url = urlparse(signal_api_url)
    if url.scheme not in ("http", "https") or not url.netloc:
        raise ConfigError(f"SIGNAL_API_URL must be an http(s) URL, got {signal_api_url!r}")

    return Env(
        signal_number=signal_number,
        flat_group_id=required("FLAT_GROUP_ID"),
        dinner_group_id=required("DINNER_GROUP_ID"),
        signal_api_url=signal_api_url.rstrip("/"),
        config_path=Path(required("ODIB_CONFIG")),
        db_path=Path(required("ODIB_DB")),
    )


# --- Schedule -----------------------------------------------------------------------------------

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MINUTES_PER_WEEK = 7 * 24 * 60


@dataclass(frozen=True)
class WeeklyTime:
    """A point in the week, in the configured timezone. `weekday` is 0 = Monday … 6 = Sunday."""

    weekday: int
    time: dt.time

    def minutes_before(self, other: WeeklyTime) -> int:
        """How many minutes this point lies before `other`, going back at most one week."""
        mine = self.weekday * 24 * 60 + self.time.hour * 60 + self.time.minute
        theirs = other.weekday * 24 * 60 + other.time.hour * 60 + other.time.minute
        return (theirs - mine) % _MINUTES_PER_WEEK

    def __str__(self) -> str:
        return f"{_WEEKDAYS[self.weekday][:3]} {self.time:%H:%M}"


@dataclass(frozen=True)
class Schedule:
    """The weekly cycle. Every point belongs to the week that ends with `dinner`."""

    flat_ask: WeeklyTime
    nudge: WeeklyTime | None  # None: nudge disabled
    flat_deadline: WeeklyTime  # also when the dinner group is told (announcement/cancellation)
    rsvp_by: WeeklyTime
    tally: WeeklyTime
    cook: WeeklyTime
    dinner: WeeklyTime


_DEFAULT_SCHEDULE: dict[str, tuple[str, str]] = {
    "flat_ask": ("tue", "18:00"),
    "nudge": ("wed", "12:00"),
    "flat_deadline": ("wed", "18:00"),
    "rsvp_by": ("fri", "14:00"),
    "tally": ("fri", "14:00"),
    "cook": ("sun", "17:00"),
    "dinner": ("sun", "18:00"),
}


def _parse_weekday(value: object, where: str) -> int:
    if isinstance(value, str):
        name = value.strip().lower()
        for i, full in enumerate(_WEEKDAYS):
            if name in (full, full[:3]):
                return i
    raise ConfigError(f"{where}: unknown weekday {value!r} (use mon, tue, … or monday, …)")


def _parse_time(value: object, where: str) -> dt.time:
    if isinstance(value, dt.time):
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"\d{1,2}:\d{2}", value.strip()):
        hour, minute = (int(part) for part in value.strip().split(":"))
        try:
            parsed = dt.time(hour, minute)
        except ValueError:
            raise ConfigError(f"{where}: invalid time {value!r}") from None
    else:
        raise ConfigError(f'{where}: invalid time {value!r} (use "HH:MM")')
    if parsed.second or parsed.microsecond:
        raise ConfigError(f"{where}: times must be whole minutes, got {value!r}")
    return parsed


def _parse_weekly_time(
    raw: object, default: tuple[str, str], where: str, *, can_disable: bool = False
) -> WeeklyTime | None:
    table = _table(raw, where)
    allowed = {"weekday", "time"} | ({"enabled"} if can_disable else set())
    _reject_unknown(table, allowed, where)
    if can_disable:
        enabled = table.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"{where}.enabled: must be true or false, got {enabled!r}")
        if not enabled:
            return None
    return WeeklyTime(
        weekday=_parse_weekday(table.get("weekday", default[0]), f"{where}.weekday"),
        time=_parse_time(table.get("time", default[1]), f"{where}.time"),
    )


def _parse_schedule(raw: object) -> Schedule:
    table = _table(raw, "schedule")
    _reject_unknown(table, set(_DEFAULT_SCHEDULE), "schedule")
    points = {
        name: _parse_weekly_time(
            table.get(name), default, f"schedule.{name}", can_disable=name == "nudge"
        )
        for name, default in _DEFAULT_SCHEDULE.items()
    }
    schedule = Schedule(**points)  # ty: ignore[invalid-argument-type]
    _check_order(schedule)
    return schedule


def _check_order(s: Schedule) -> None:
    """The points must follow each other within the week that ends with dinner."""
    dinner = s.dinner

    def before(a: WeeklyTime, b: WeeklyTime) -> bool:
        return a.minutes_before(dinner) > b.minutes_before(dinner)

    def not_after(a: WeeklyTime, b: WeeklyTime) -> bool:
        return a.minutes_before(dinner) >= b.minutes_before(dinner)

    rules: list[tuple[str, str, bool]] = [
        ("flat_ask", "flat_deadline", before(s.flat_ask, s.flat_deadline)),
        ("flat_deadline", "rsvp_by", not_after(s.flat_deadline, s.rsvp_by)),
        ("flat_deadline", "tally", before(s.flat_deadline, s.tally)),
        ("tally", "dinner", before(s.tally, dinner)),
        ("flat_deadline", "cook", before(s.flat_deadline, s.cook)),
    ]
    if s.nudge is not None:
        rules += [
            ("flat_ask", "nudge", before(s.flat_ask, s.nudge)),
            ("nudge", "flat_deadline", before(s.nudge, s.flat_deadline)),
        ]
    for first, second, ok in rules:
        if not ok:
            raise ConfigError(
                f"schedule: {first} ({getattr(s, first)}) must come before {second} "
                f"({getattr(s, second)}) in the week leading up to dinner ({dinner})"
            )


# --- Templates ----------------------------------------------------------------------------------

# Placeholders every template may use. Times are rendered as "HH:MM".
COMMON_PLACEHOLDERS = frozenset({"emoji", "deadline", "rsvp_by", "cook_time", "dinner_time"})

# Template name -> placeholders it may use. Templates have no defaults: texts live in the config.
TEMPLATE_PLACEHOLDERS: dict[str, frozenset[str]] = {
    "flat_ask": COMMON_PLACEHOLDERS,  # flat group, German
    "nudge": COMMON_PLACEHOLDERS,  # flat group, German
    "cancellation": COMMON_PLACEHOLDERS,  # dinner group, bilingual
    "announcement": COMMON_PLACEHOLDERS,  # dinner group, bilingual
    "tally": COMMON_PLACEHOLDERS | {"count"},  # flat group, German
}


@dataclass(frozen=True)
class Template:
    """A message text with `{placeholder}`s, checked against the allowed set at load time."""

    text: str
    placeholders: frozenset[str]  # the placeholders `text` actually uses

    @classmethod
    def parse(cls, text: str, allowed: frozenset[str], where: str) -> Template:
        used: set[str] = set()
        try:
            parsed = list(string.Formatter().parse(text))
        except ValueError as e:
            raise ConfigError(
                f"{where}: malformed template ({e}); write {{{{ for a literal {{"
            ) from None
        for _, field, spec, conversion in parsed:
            if field is None:
                continue
            if field not in allowed:
                raise ConfigError(
                    f"{where}: unknown placeholder {{{field}}}; allowed: "
                    + ", ".join(f"{{{name}}}" for name in sorted(allowed))
                )
            if spec or conversion:
                raise ConfigError(f"{where}: placeholder {{{field}}} must not have a format spec")
            used.add(field)
        return cls(text=text, placeholders=frozenset(used))

    def render(self, **values: object) -> str:
        missing = self.placeholders - values.keys()
        if missing:
            raise KeyError(f"missing template values: {', '.join(sorted(missing))}")
        return self.text.format_map(values)


@dataclass(frozen=True)
class Templates:
    flat_ask: Template
    nudge: Template
    cancellation: Template
    announcement: Template
    tally: Template


def _parse_templates(raw: object) -> Templates:
    table = _table(raw, "templates")
    _reject_unknown(table, set(TEMPLATE_PLACEHOLDERS), "templates")
    parsed: dict[str, Template] = {}
    for name, allowed in TEMPLATE_PLACEHOLDERS.items():
        where = f"templates.{name}"
        text = table.get(name)
        if not isinstance(text, str) or not text.strip():
            raise ConfigError(f"{where}: missing or empty message text")
        parsed[name] = Template.parse(text.strip(), allowed, where)
    return Templates(**parsed)


# --- Config -------------------------------------------------------------------------------------

DEFAULT_TIMEZONE = "Europe/Berlin"
DEFAULT_EMOJI = "👍"
UNTIL_DINNER = "until_dinner"


@dataclass(frozen=True)
class Config:
    """Behaviour from the TOML config file."""

    timezone: ZoneInfo
    emoji: str
    # How late a missed action may still be performed. None: until dinner starts.
    catch_up_grace: dt.timedelta | None
    schedule: Schedule
    templates: Templates

    def placeholder_values(self) -> dict[str, str]:
        """Values for COMMON_PLACEHOLDERS; message-specific ones (e.g. count) are added later."""
        s = self.schedule
        return {
            "emoji": self.emoji,
            "deadline": f"{s.flat_deadline.time:%H:%M}",
            "rsvp_by": f"{s.rsvp_by.time:%H:%M}",
            "cook_time": f"{s.cook.time:%H:%M}",
            "dinner_time": f"{s.dinner.time:%H:%M}",
        }


def parse_config(data: Mapping[str, Any]) -> Config:
    _reject_unknown(
        data, {"timezone", "emoji", "catch_up_grace", "schedule", "templates"}, "config"
    )

    tz_name = data.get("timezone", DEFAULT_TIMEZONE)
    try:
        if not isinstance(tz_name, str):
            raise ValueError
        timezone = ZoneInfo(tz_name)
    except ValueError, ZoneInfoNotFoundError:
        raise ConfigError(f"timezone: unknown timezone {tz_name!r}") from None

    emoji = data.get("emoji", DEFAULT_EMOJI)
    if not isinstance(emoji, str) or not emoji.strip():
        raise ConfigError(f"emoji: must be a non-empty string, got {emoji!r}")

    grace = data.get("catch_up_grace", UNTIL_DINNER)
    catch_up_grace: dt.timedelta | None
    if grace == UNTIL_DINNER:
        catch_up_grace = None
    elif isinstance(grace, int) and not isinstance(grace, bool) and grace > 0:
        catch_up_grace = dt.timedelta(minutes=grace)
    else:
        raise ConfigError(
            f"catch_up_grace: must be {UNTIL_DINNER!r} or a positive number of minutes, "
            f"got {grace!r}"
        )

    return Config(
        timezone=timezone,
        emoji=emoji.strip(),
        catch_up_grace=catch_up_grace,
        schedule=_parse_schedule(data.get("schedule")),
        templates=_parse_templates(data.get("templates")),
    )


def load_config(path: Path) -> Config:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        raise ConfigError(f"cannot read config file {path}: {e}") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML in {path}: {e}") from None
    return parse_config(data)


# --- Settings -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    env: Env
    config: Config


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Load env vars (default: the process environment) and the config file they point to."""
    env = load_env(os.environ if environ is None else environ)
    return Settings(env=env, config=load_config(env.config_path))


# --- Helpers ------------------------------------------------------------------------------------


def _table(raw: object, where: str) -> Mapping[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{where}: must be a table, got {raw!r}")
    return raw


def _reject_unknown(table: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(
            f"{where}: unknown key(s) {', '.join(unknown)}; allowed: {', '.join(sorted(allowed))}"
        )
