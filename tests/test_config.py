import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from odib.config import (
    DEFAULT_SIGNAL_API_URL,
    ConfigError,
    WeeklyTime,
    load_config,
    load_env,
    load_settings,
    parse_config,
)

EXAMPLE = Path(__file__).parent.parent / "config.example.toml"

TEMPLATES = {
    "flat_ask": "Abendessen? {emoji} bis {deadline}",
    "nudge": "Noch kein {emoji}",
    "cancellation": "Abgesagt.\n\nCancelled.",
    "announcement": "Kochen {cook_time}, Essen {dinner_time}, {emoji} bis {rsvp_by}",
    "tally": "{count} mal {emoji}",
    "hello": "Hallo, bitte antworte.",
    "flat_test": "Test, {emoji}",
}

ENV = {
    "SIGNAL_NUMBER": "+491701234567",
    "FLAT_GROUP_ID": "ZmxhdA==",
    "DINNER_GROUP_ID": "ZGlubmVy",
    "SIGNAL_API_URL": "http://signal:8080/",
    "ODIB_CONFIG": "/config/config.toml",
    "ODIB_DB": "/data/odib.sqlite3",
}


def config(**overrides: Any) -> dict[str, Any]:
    return {"templates": dict(TEMPLATES), **overrides}


# --- defaults -----------------------------------------------------------------------------------


def test_defaults() -> None:
    c = parse_config(config())
    assert c.timezone.key == "Europe/Berlin"
    assert c.emoji == "👍"
    assert c.catch_up_grace is None
    s = c.schedule
    assert s.flat_ask == WeeklyTime(1, dt.time(18, 0))
    assert s.nudge == WeeklyTime(2, dt.time(12, 0))
    assert s.flat_deadline == WeeklyTime(2, dt.time(18, 0))
    assert s.rsvp_by == WeeklyTime(4, dt.time(14, 0))
    assert s.tally == WeeklyTime(4, dt.time(14, 0))
    assert s.cook == WeeklyTime(6, dt.time(17, 0))
    assert s.dinner == WeeklyTime(6, dt.time(18, 0))


def test_example_config_loads_and_matches_defaults() -> None:
    c = load_config(EXAMPLE)
    defaults = parse_config(config())
    assert (c.timezone, c.emoji, c.catch_up_grace, c.schedule) == (
        defaults.timezone,
        defaults.emoji,
        defaults.catch_up_grace,
        defaults.schedule,
    )
    values = c.placeholder_values()
    for name in ("flat_ask", "nudge", "cancellation", "announcement"):
        assert getattr(c.templates, name).render(**values)
    assert "7" in c.templates.tally.render(**values, count=7)


def test_example_dinner_texts_are_bilingual() -> None:
    c = load_config(EXAMPLE)
    for template in (c.templates.announcement, c.templates.cancellation):
        german, english = template.text.split("\n\n")
        assert "Sonntag" in german
        assert "Sunday" in english


def test_example_announcement_content() -> None:
    c = load_config(EXAMPLE)
    text = c.templates.announcement.render(**c.placeholder_values())
    assert "17:00" in text
    assert "18:00" in text
    assert "Freitag 14:00" in text
    assert "Friday 14:00" in text
    assert "freiwillig" in text
    assert "optional" in text


# --- overriding ---------------------------------------------------------------------------------


def test_override_schedule() -> None:
    c = parse_config(
        config(
            timezone="Europe/Vienna",
            emoji="❤️",
            catch_up_grace=90,
            schedule={
                "flat_ask": {"weekday": "Monday", "time": "9:30"},
                "nudge": {"enabled": False},
                "tally": {"weekday": "sat", "time": dt.time(10, 0)},
                "dinner": {"time": "19:00"},
            },
        )
    )
    assert c.timezone.key == "Europe/Vienna"
    assert c.emoji == "❤️"
    assert c.catch_up_grace == dt.timedelta(minutes=90)
    s = c.schedule
    assert s.flat_ask == WeeklyTime(0, dt.time(9, 30))
    assert s.nudge is None
    assert s.tally == WeeklyTime(5, dt.time(10, 0))
    assert s.dinner == WeeklyTime(6, dt.time(19, 0))
    assert s.flat_deadline == WeeklyTime(2, dt.time(18, 0))  # untouched default
    assert c.placeholder_values()["dinner_time"] == "19:00"


def test_dinner_on_another_weekday() -> None:
    sched = {
        "flat_ask": {"weekday": "fri"},
        "nudge": {"weekday": "sat"},
        "flat_deadline": {"weekday": "sat"},
        "rsvp_by": {"weekday": "mon"},
        "tally": {"weekday": "mon"},
        "cook": {"weekday": "wed"},
        "dinner": {"weekday": "wed"},
    }
    assert parse_config(config(schedule=sched)).schedule.dinner.weekday == 2


def test_config_is_immutable() -> None:
    c = parse_config(config())
    with pytest.raises(AttributeError):
        c.emoji = "x"  # ty: ignore[invalid-assignment]


# --- invalid schedule ---------------------------------------------------------------------------


@pytest.mark.parametrize("weekday", ["funday", "", 3, "mo"])
def test_invalid_weekday(weekday: object) -> None:
    with pytest.raises(ConfigError, match=r"schedule\.tally\.weekday"):
        parse_config(config(schedule={"tally": {"weekday": weekday}}))


@pytest.mark.parametrize("time", ["25:00", "12:60", "noon", "1800", 1800, "12:00:30"])
def test_invalid_time(time: object) -> None:
    with pytest.raises(ConfigError, match=r"schedule\.cook\.time"):
        parse_config(config(schedule={"cook": {"time": time}}))


def test_time_with_seconds_rejected() -> None:
    with pytest.raises(ConfigError, match="whole minutes"):
        parse_config(config(schedule={"cook": {"time": dt.time(17, 0, 30)}}))


@pytest.mark.parametrize(
    ("schedule", "message"),
    [
        ({"nudge": {"weekday": "wed", "time": "19:00"}}, "nudge .* before flat_deadline"),
        ({"flat_ask": {"weekday": "wed", "time": "13:00"}}, "flat_ask .* before nudge"),
        ({"tally": {"weekday": "wed", "time": "17:00"}}, "flat_deadline .* before tally"),
        ({"cook": {"weekday": "sun", "time": "19:00"}}, "flat_deadline .* before cook"),
        ({"rsvp_by": {"weekday": "tue", "time": "19:00"}}, "flat_deadline .* before rsvp_by"),
    ],
)
def test_schedule_out_of_order(schedule: dict[str, Any], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_config(config(schedule=schedule))


def test_unknown_schedule_key() -> None:
    with pytest.raises(ConfigError, match=r"unknown key.*nuge"):
        parse_config(config(schedule={"nuge": {"enabled": False}}))


def test_only_nudge_can_be_disabled() -> None:
    with pytest.raises(ConfigError, match=r"schedule\.tally: unknown key.*enabled"):
        parse_config(config(schedule={"tally": {"enabled": False}}))


@pytest.mark.parametrize(
    ("overrides", "where"),
    [
        ({"timezone": "Mars/Olympus"}, "timezone"),
        ({"emoji": ""}, "emoji"),
        ({"catch_up_grace": 0}, "catch_up_grace"),
        ({"catch_up_grace": "forever"}, "catch_up_grace"),
        ({"colour": "blue"}, "unknown key"),
    ],
)
def test_invalid_top_level(overrides: dict[str, Any], where: str) -> None:
    with pytest.raises(ConfigError, match=where):
        parse_config(config(**overrides))


# --- templates ----------------------------------------------------------------------------------


def test_unknown_placeholder() -> None:
    templates = {**TEMPLATES, "announcement": "Essen um {dinnertime}"}
    with pytest.raises(ConfigError, match=r"templates\.announcement: unknown placeholder"):
        parse_config({"templates": templates})


def test_count_only_in_tally() -> None:
    templates = {**TEMPLATES, "nudge": "{count} Leute"}
    with pytest.raises(ConfigError, match=r"templates\.nudge: unknown placeholder \{count\}"):
        parse_config({"templates": templates})


@pytest.mark.parametrize(
    "text", ["{}", "{0}", "{emoji.real}", "{emoji!r}", "{count:>3}", "{emoji", "a } b"]
)
def test_bad_placeholder_syntax(text: str) -> None:
    with pytest.raises(ConfigError, match=r"templates\.tally"):
        parse_config({"templates": {**TEMPLATES, "tally": text}})


def test_literal_braces() -> None:
    c = parse_config({"templates": {**TEMPLATES, "tally": "{{{count}}}"}})
    assert c.templates.tally.render(count=3) == "{3}"


@pytest.mark.parametrize("name", list(TEMPLATES))
def test_missing_template(name: str) -> None:
    templates = {k: v for k, v in TEMPLATES.items() if k != name}
    with pytest.raises(ConfigError, match=rf"templates\.{name}: missing"):
        parse_config({"templates": templates})


def test_render_requires_used_values() -> None:
    c = parse_config(config())
    with pytest.raises(KeyError, match="count"):
        c.templates.tally.render(emoji="👍")


# --- file loading -------------------------------------------------------------------------------


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "nope.toml")


def test_invalid_toml(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("timezone = ")
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(path)


# --- env ----------------------------------------------------------------------------------------


def test_env() -> None:
    env = load_env(ENV)
    assert env.signal_number == "+491701234567"
    assert env.flat_group_id == "ZmxhdA=="
    assert env.dinner_group_id == "ZGlubmVy"
    assert env.signal_api_url == "http://signal:8080"
    assert env.config_path == Path("/config/config.toml")
    assert env.db_path == Path("/data/odib.sqlite3")


def test_env_default_api_url() -> None:
    env = load_env({k: v for k, v in ENV.items() if k != "SIGNAL_API_URL"})
    assert env.signal_api_url == DEFAULT_SIGNAL_API_URL


@pytest.mark.parametrize("name", ["SIGNAL_NUMBER", "ODIB_CONFIG", "ODIB_DB"])
def test_missing_env_var(name: str) -> None:
    with pytest.raises(ConfigError, match=name):
        load_env({k: v for k, v in ENV.items() if k != name})


def test_blank_env_var_counts_as_missing() -> None:
    with pytest.raises(ConfigError, match="ODIB_DB"):
        load_env({**ENV, "ODIB_DB": "  "})


def test_group_ids_are_optional() -> None:
    env = load_env({k: v for k, v in ENV.items() if not k.endswith("_GROUP_ID")})
    assert (env.flat_group_id, env.dinner_group_id) == (None, None)
    assert load_env({**ENV, "FLAT_GROUP_ID": "  "}).flat_group_id is None


@pytest.mark.parametrize("number", ["01701234567", "+49 170 1234567", "+0123456789"])
def test_invalid_signal_number(number: str) -> None:
    with pytest.raises(ConfigError, match=r"E\.164"):
        load_env({**ENV, "SIGNAL_NUMBER": number})


def test_invalid_api_url() -> None:
    with pytest.raises(ConfigError, match="SIGNAL_API_URL"):
        load_env({**ENV, "SIGNAL_API_URL": "signal:8080"})


def test_load_settings(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(EXAMPLE.read_bytes())
    settings = load_settings({**ENV, "ODIB_CONFIG": str(path)})
    assert settings.env.config_path == path
    assert settings.config.emoji == "👍"


# --- profile ------------------------------------------------------------------------------------


def test_profile_defaults() -> None:
    profile = parse_config(config()).profile
    assert (profile.name, profile.avatar) == ("Odin 🍽️", None)


def test_profile_avatar_resolves_against_the_config_dir(tmp_path: Path) -> None:
    (tmp_path / "odin.png").write_bytes(b"png")
    path = tmp_path / "config.toml"
    path.write_text(EXAMPLE.read_text().replace('# avatar = "odin.png"', 'avatar = "odin.png"'))
    assert load_config(path).profile.avatar == tmp_path / "odin.png"


def test_profile_avatar_must_exist(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"profile\.avatar: no such file"):
        parse_config(config(profile={"avatar": "missing.png"}), base_dir=tmp_path)


@pytest.mark.parametrize("profile", [{"name": ""}, {"name": 3}, {"nick": "Odin"}, {"avatar": 1}])
def test_invalid_profile(profile: dict[str, Any]) -> None:
    with pytest.raises(ConfigError, match="profile"):
        parse_config(config(profile=profile))


# --- when ---------------------------------------------------------------------------------------


def test_when_places_points_in_the_dinner_week() -> None:
    c = parse_config(config())
    berlin = c.timezone
    sunday = dt.date(2026, 10, 11)
    assert c.when(c.schedule.flat_ask, sunday) == dt.datetime(2026, 10, 6, 18, 0, tzinfo=berlin)
    assert c.when(c.schedule.tally, sunday) == dt.datetime(2026, 10, 9, 14, 0, tzinfo=berlin)
    assert c.when(c.schedule.dinner, sunday) == dt.datetime(2026, 10, 11, 18, 0, tzinfo=berlin)


def test_when_keeps_local_time_across_dst() -> None:
    c = parse_config(config())
    sunday = dt.date(2026, 10, 25)  # summer time ends at 03:00 that morning
    deadline = c.when(c.schedule.flat_deadline, sunday)
    dinner = c.when(c.schedule.dinner, sunday)
    assert (deadline.hour, deadline.utcoffset()) == (18, dt.timedelta(hours=2))
    assert (dinner.hour, dinner.utcoffset()) == (18, dt.timedelta(hours=1))


def test_when_rejects_a_day_without_dinner() -> None:
    c = parse_config(config())
    with pytest.raises(ValueError, match="not a dinner day"):
        c.when(c.schedule.flat_ask, dt.date(2026, 10, 10))
