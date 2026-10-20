from datetime import UTC, datetime

from odin.commands import CommandContext, handle
from odin.commands.schedule import POINT_DESCRIPTIONS
from odin.config import Config, parse_config
from odin.cycle import SchedulePoint
from odin.overrides import NUDGE_ENABLED_KEY, effective_config, schedule_key
from odin.store import Store

TEMPLATES = {
    "flat_ask": "Abendessen? {emoji} bis {deadline}",
    "nudge": "Noch kein {emoji}",
    "cancellation": "Abgesagt.\n\nCancelled.",
    "announcement": "Kochen {cook_time}, Essen {dinner_time}, {emoji} bis {rsvp_by}",
    "tally": "{count} mal {emoji}",
    "hello": "Hallo",
    "flat_test": "Test",
}
CONFIG = parse_config({"templates": TEMPLATES})
NUDGE_OFF_CONFIG = parse_config({"templates": TEMPLATES, "schedule": {"nudge": {"enabled": False}}})
NOW = datetime(2026, 10, 6, 19, 0, tzinfo=CONFIG.timezone)
FOOTER = "Ändern: /settime <punkt> <tag> <HH:MM> · Zurücksetzen: /resettime <punkt>"
DEFAULT_LINES = [
    "flat_ask – Frage an die WG: Di 18:00",
    "nudge – Erinnerung: Mi 12:00",
    "flat_deadline – Entscheidung: Mi 18:00",
    "rsvp_by – Rückmeldung bis: Fr 14:00",
    "tally – Zählung: Fr 14:00",
    "cook – Mitkochen: So 17:00",
    "dinner – Essen: So 18:00",
]


def context(store: Store, base: Config = CONFIG) -> CommandContext:
    return CommandContext(
        base=base,
        config=effective_config(base, store, NOW),
        store=store,
        now=NOW,
        sender="+4915100000001",
        sender_name="Anna",
    )


def schedule(store: Store, base: Config = CONFIG) -> list[str]:
    [reply] = handle("/schedule", context(store, base))
    return reply.splitlines()


def test_descriptions_cover_every_point_in_order() -> None:
    assert tuple(POINT_DESCRIPTIONS) == tuple(SchedulePoint)


def test_defaults(store: Store) -> None:
    assert schedule(store) == [*DEFAULT_LINES, "", FOOTER]


def test_bang_prefix_and_args_are_ignored(store: Store) -> None:
    ctx = context(store)
    assert handle("!schedule", ctx) == handle("/schedule", ctx) == handle("/schedule x", ctx)


def test_schedule_override_is_marked(store: Store) -> None:
    # 22:30 UTC on 11 Oct is already 12 Oct in Berlin.
    changed_at = datetime(2026, 10, 11, 22, 30, tzinfo=UTC)
    store.set_override(schedule_key(SchedulePoint.RSVP_BY), "thu 20:00", "Tim", changed_at)
    lines = schedule(store)
    assert lines[3] == "rsvp_by – Rückmeldung bis: Do 20:00 ✏️ 12.10. von Tim"
    assert lines[:3] + lines[4:7] == DEFAULT_LINES[:3] + DEFAULT_LINES[4:]


def test_marker_shows_whatever_was_stored_as_changed_by(store: Store) -> None:
    store.set_override(schedule_key(SchedulePoint.DINNER), "sun 19:00", "+4915100000002", NOW)
    assert schedule(store)[6] == "dinner – Essen: So 19:00 ✏️ 06.10. von +4915100000002"


def test_nudge_disabled_by_the_toml(store: Store) -> None:
    lines = schedule(store, NUDGE_OFF_CONFIG)
    assert lines[1] == "nudge – Erinnerung: Mi 12:00 (aus)"
    assert lines[2:7] == DEFAULT_LINES[2:]


def test_nudge_disabled_by_an_override(store: Store) -> None:
    store.set_override(NUDGE_ENABLED_KEY, "false", "Tim", NOW)
    assert schedule(store)[1] == "nudge – Erinnerung: Mi 12:00 (aus) ✏️ 06.10. von Tim"


def test_nudge_enabled_by_an_override(store: Store) -> None:
    store.set_override(NUDGE_ENABLED_KEY, "true", "Tim", NOW)
    assert schedule(store, NUDGE_OFF_CONFIG)[1] == "nudge – Erinnerung: Mi 12:00 ✏️ 06.10. von Tim"


def test_nudge_shows_its_latest_change(store: Store) -> None:
    earlier = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    later = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    store.set_override(schedule_key(SchedulePoint.NUDGE), "wed 10:00", "Anna", earlier)
    store.set_override(NUDGE_ENABLED_KEY, "false", "Tim", later)
    assert schedule(store)[1] == "nudge – Erinnerung: Mi 10:00 (aus) ✏️ 06.10. von Tim"
