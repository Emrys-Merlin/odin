import datetime as dt
import logging
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from odin.config import Config, ConfigError, WeeklyTime, parse_config
from odin.overrides import (
    EDITABLE_TEMPLATES,
    KEYS,
    NUDGE_ENABLED_KEY,
    SCHEDULE_POINTS,
    apply_overrides,
    effective_config,
    format_bool,
    format_weekly_time,
    schedule_key,
    template_key,
)
from odin.store import Store

TEMPLATES = {
    "flat_ask": "ASK {emoji} bis {deadline}",
    "nudge": "NUDGE {deadline}",
    "cancellation": "ABGESAGT\n\nCANCELLED",
    "announcement": "ESSEN {dinner_time}\n\nDINNER {dinner_time}",
    "tally": "TALLY {count} x {emoji}",
    "hello": "HELLO",
    "flat_test": "TEST",
}
NOW = datetime(2026, 10, 6, 19, 0, tzinfo=timezone(timedelta(hours=2)))


def make_config(**overrides: Any) -> Config:
    return parse_config({"templates": TEMPLATES, **overrides})


BASE = make_config()


@pytest.fixture
def store() -> Iterator[Store]:
    with Store(":memory:") as s:
        yield s


# --- keys ---------------------------------------------------------------------------------------


def test_keys() -> None:
    assert template_key("flat_ask") == "templates.flat_ask"
    assert schedule_key("flat_deadline") == "schedule.flat_deadline"
    assert NUDGE_ENABLED_KEY == "schedule.nudge.enabled"
    assert len(KEYS) == len(EDITABLE_TEMPLATES) + len(SCHEDULE_POINTS) + 1
    with pytest.raises(ValueError, match="hello"):
        template_key("hello")
    with pytest.raises(ValueError, match="lunch"):
        schedule_key("lunch")


def test_formatted_values_round_trip() -> None:
    point = WeeklyTime(5, dt.time(9, 5))
    assert format_weekly_time(point) == "sat 09:05"
    config = apply_overrides(BASE, {schedule_key("tally"): format_weekly_time(point)})
    assert config.schedule.tally == point
    assert format_bool(False) == "false"
    config = apply_overrides(BASE, {NUDGE_ENABLED_KEY: format_bool(False)})
    assert config.schedule.nudge is None


# --- apply_overrides ----------------------------------------------------------------------------


def test_no_overrides_change_nothing() -> None:
    assert apply_overrides(BASE, {}) == BASE


def test_template_override() -> None:
    config = apply_overrides(BASE, {"templates.tally": "\n{count} kommen {emoji}\n\n"})
    assert config.templates.tally.text == "{count} kommen {emoji}"
    assert config.templates.tally.render(count=3, emoji="👍") == "3 kommen 👍"
    assert config.templates.nudge == BASE.templates.nudge
    assert config.schedule == BASE.schedule


@pytest.mark.parametrize(
    ("key", "value", "error"),
    [
        ("templates.nudge", "{count} fehlen", r"templates\.nudge: unknown placeholder \{count\}"),
        ("templates.flat_ask", "Kommt {wer}?", r"unknown placeholder \{wer\}"),
        ("templates.flat_ask", "Klammer {", "malformed template"),
        ("templates.flat_ask", "  \n", "empty"),
        ("templates.hello", "Hi", "unknown override 'templates.hello'"),
        ("schedule.tally", "sat", "<weekday> <HH:MM>"),
        ("schedule.tally", "samstag 10:00", "unknown weekday"),
        ("schedule.tally", "sat 25:00", "invalid time"),
        ("schedule.nudge.enabled", "yes", 'must be "true" or "false"'),
        ("emoji", "❤️", "unknown override 'emoji'"),
    ],
)
def test_invalid_override_is_rejected(key: str, value: str, error: str) -> None:
    with pytest.raises(ConfigError, match=error):
        apply_overrides(BASE, {key: value})


def test_schedule_override() -> None:
    config = apply_overrides(BASE, {"schedule.flat_deadline": "Thursday 9:30"})
    assert config.schedule.flat_deadline == WeeklyTime(3, dt.time(9, 30))
    assert config.placeholder_values()["deadline"] == "09:30"
    assert config.schedule.flat_ask == BASE.schedule.flat_ask


def test_schedule_override_that_breaks_the_order_is_rejected() -> None:
    with pytest.raises(ConfigError, match=r"flat_deadline \(fri 15:00\) must come before rsvp_by"):
        apply_overrides(BASE, {"schedule.flat_deadline": "fri 15:00"})
    # Together with matching later points it is fine.
    config = apply_overrides(
        BASE,
        {
            "schedule.flat_deadline": "fri 15:00",
            "schedule.rsvp_by": "fri 16:00",
            "schedule.tally": "fri 16:00",
        },
    )
    assert config.schedule.tally == WeeklyTime(4, dt.time(16, 0))


def test_disable_and_enable_the_nudge() -> None:
    disabled = apply_overrides(BASE, {NUDGE_ENABLED_KEY: "false"})
    assert disabled.schedule.nudge is None
    assert disabled.schedule.nudge_time == BASE.schedule.nudge_time

    enabled = apply_overrides(BASE, {NUDGE_ENABLED_KEY: "true"})
    assert enabled.schedule.nudge == BASE.schedule.nudge


def test_enable_a_nudge_the_toml_disables_keeps_its_time() -> None:
    base = make_config(schedule={"nudge": {"weekday": "wed", "time": "9:00", "enabled": False}})
    assert base.schedule.nudge is None
    config = apply_overrides(base, {NUDGE_ENABLED_KEY: "true"})
    assert config.schedule.nudge == WeeklyTime(2, dt.time(9, 0))


def test_enable_a_nudge_the_toml_disables_without_a_time() -> None:
    base = make_config(schedule={"nudge": {"enabled": False}})
    config = apply_overrides(base, {NUDGE_ENABLED_KEY: "true"})
    assert config.schedule.nudge == WeeklyTime(2, dt.time(12, 0))  # the default, wed 12:00


def test_a_disabled_nudge_is_not_order_checked() -> None:
    # Moving the deadline before the nudge is fine while the nudge is off…
    config = apply_overrides(
        BASE, {NUDGE_ENABLED_KEY: "false", "schedule.flat_deadline": "wed 11:00"}
    )
    assert config.schedule.nudge is None
    # …but enabling it then breaks the order.
    with pytest.raises(ConfigError, match=r"nudge \(wed 12:00\) must come before flat_deadline"):
        apply_overrides(BASE, {"schedule.flat_deadline": "wed 11:00"})


def test_nudge_time_override() -> None:
    config = apply_overrides(BASE, {"schedule.nudge": "wed 8:00"})
    assert config.schedule.nudge == WeeklyTime(2, dt.time(8, 0))


# --- effective_config ---------------------------------------------------------------------------


def test_effective_config_without_overrides_is_the_base(store: Store) -> None:
    assert effective_config(BASE, store, NOW) is BASE


def test_effective_config_applies_stored_overrides(store: Store) -> None:
    store.set_override("schedule.tally", "sat 10:00", "Tim", NOW)
    store.set_override("templates.cancellation", "AUS\n\nOFF", "Tim", NOW)
    config = effective_config(BASE, store, NOW)
    assert config.schedule.tally == WeeklyTime(5, dt.time(10, 0))
    assert config.templates.cancellation.text == "AUS\n\nOFF"


def test_invalid_stored_overrides_are_dropped(
    store: Store, caplog: pytest.LogCaptureFixture
) -> None:
    store.set_override("schedule.flat_deadline", "thu 18:00", "Tim", NOW)
    store.set_override("schedule.rsvp_by", "fri 12:00", "Tim", NOW + timedelta(minutes=1))
    store.set_override("templates.nudge", "NUDGE", "Anna", NOW + timedelta(minutes=2))
    # Cannot happen via chat (it is validated first), but e.g. after a code change.
    store.set_override("templates.flat_ask", "Kommt {wer}?", "Ben", NOW + timedelta(minutes=3))

    # The TOML changes underneath: the tally moves before the overridden deadline.
    base = make_config(schedule={"tally": {"weekday": "thu", "time": "12:00"}})
    with caplog.at_level(logging.WARNING):
        config = effective_config(base, store, NOW)

    assert config.schedule.flat_deadline == base.schedule.flat_deadline
    assert config.schedule.rsvp_by == WeeklyTime(4, dt.time(12, 0))
    assert config.templates.flat_ask == base.templates.flat_ask
    assert config.templates.nudge.text == "NUDGE"
    assert set(store.overrides()) == {"schedule.rsvp_by", "templates.nudge"}
    warned = [r.getMessage() for r in caplog.records]
    assert len(warned) == 2
    assert "schedule.flat_deadline" in warned[0]
    assert "templates.flat_ask" in warned[1]

    # Dropped for good: no warnings on the next call.
    caplog.clear()
    assert effective_config(base, store, NOW) == config
    assert not caplog.records


def test_of_two_conflicting_overrides_the_newer_is_dropped(store: Store) -> None:
    # Each is valid on its own against the TOML, but not together.
    store.set_override("schedule.flat_deadline", "thu 18:00", "Tim", NOW)
    store.set_override("schedule.rsvp_by", "thu 12:00", "Anna", NOW + timedelta(minutes=1))
    config = effective_config(BASE, store, NOW)
    assert config.schedule.flat_deadline == WeeklyTime(3, dt.time(18, 0))
    assert config.schedule.rsvp_by == BASE.schedule.rsvp_by
    assert set(store.overrides()) == {"schedule.flat_deadline"}


def test_unknown_stored_key_is_dropped(store: Store, caplog: pytest.LogCaptureFixture) -> None:
    store.set_override("emoji", "❤️", "Tim", NOW)
    with caplog.at_level(logging.WARNING):
        assert effective_config(BASE, store, NOW) == BASE
    assert "emoji" in caplog.text
    assert store.overrides() == {}
