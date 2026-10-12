from collections.abc import Iterator
from datetime import date, datetime

import pytest

from odin.commands import CommandContext, handle
from odin.commands.status import STEP_LABELS
from odin.config import Config, parse_config
from odin.engine import upcoming_actions
from odin.store import Action, MessageKind, Outcome, Store

TEMPLATES = {
    "flat_ask": "Essen? {emoji} bis {deadline}",
    "nudge": "Noch kein {emoji}",
    "cancellation": "Abgesagt.\n\nCancelled.",
    "announcement": "Essen {dinner_time}\n\nDinner {dinner_time}",
    "tally": "{count} mal {emoji}",
    "hello": "Hallo",
    "flat_test": "Test",
}
# Default schedule: ask Tue 18:00, nudge Wed 12:00, decision Wed 18:00, tally Fri 14:00,
# dinner Sun 18:00.
CONFIG = parse_config({"templates": TEMPLATES})
NO_NUDGE = parse_config({"templates": TEMPLATES, "schedule": {"nudge": {"enabled": False}}})
BERLIN = CONFIG.timezone

# Dinner on Sunday 2026-10-18; flat ask on Tuesday 2026-10-13.
WEEK = date(2026, 10, 18)
BOT = "+490000000000"
FLAT, DINNER = "group.flat=", "group.dinner="
ANNA, BEN, CARL = "+4915100000001", "+4915100000002", "+4915100000003"


def local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=BERLIN)


@pytest.fixture
def store() -> Iterator[Store]:
    with Store(":memory:") as s:
        yield s


def status(store: Store, now: datetime, config: Config = CONFIG) -> list[str]:
    ctx = CommandContext(
        base=config, config=config, store=store, now=now, sender=ANNA, sender_name="Anna"
    )
    [reply] = handle("/status", ctx)
    return reply.splitlines()


# What the engine records, written directly.

ASK_TIME = local(13, 18)


def ask(store: Store, *reactors: str, at: datetime = ASK_TIME) -> None:
    store.record_action(WEEK, Action.FLAT_ASK, at)
    poll = store.track_message(WEEK, MessageKind.FLAT_POLL, FLAT, BOT, 1_000)
    for reactor in reactors:
        store.set_reaction(poll, reactor, "👍", at)


def announce(store: Store, *reactors: str) -> None:
    store.record_action(WEEK, Action.ANNOUNCEMENT, local(14, 18))
    message = store.track_message(WEEK, MessageKind.DINNER_ANNOUNCEMENT, DINNER, BOT, 2_000)
    for reactor in reactors:
        store.set_reaction(message, reactor, "👍", local(15, 9))


def skip(store: Store, action: Action, at: datetime) -> None:
    store.record_action(WEEK, action, at, Outcome.SKIPPED)


def test_before_the_ask(store: Store) -> None:
    assert status(store, local(12, 10)) == [
        "Sonntag, 18.10.",
        "⏳ Frage an die WG: Di 18:00",
        "⏳ Erinnerung: Mi 12:00",
        "⏳ Entscheidung: Mi 18:00",
        "⏳ Zählung: Fr 14:00",
        "Nächste Aktion: Frage an die WG, Di 18:00",
    ]


def test_after_the_ask_without_confirmations(store: Store) -> None:
    ask(store)
    assert status(store, local(13, 20)) == [
        "Sonntag, 18.10.",
        "✅ Frage an die WG gesendet (Di 18:00) – 0× 👍",
        "⏳ Erinnerung: Mi 12:00",
        "⏳ Entscheidung: Mi 18:00",
        "⏳ Zählung: Fr 14:00",
        "Nächste Aktion: Erinnerung, Mi 12:00 (nur falls noch kein 👍)",
    ]


def test_after_the_ask_with_two_confirmations(store: Store) -> None:
    ask(store, ANNA, BEN)
    lines = status(store, local(13, 20))
    assert lines[1] == "✅ Frage an die WG gesendet (Di 18:00) – 2× 👍"
    # The nudge won't be sent while someone has confirmed.
    assert lines[-1] == "Nächste Aktion: Entscheidung, Mi 18:00"


def test_shows_when_a_late_step_was_actually_sent(store: Store) -> None:
    ask(store, at=local(13, 19, 5))
    assert status(store, local(13, 20))[1] == "✅ Frage an die WG gesendet (Di 19:05) – 0× 👍"


def test_after_the_nudge(store: Store) -> None:
    ask(store)
    store.record_action(WEEK, Action.NUDGE, local(14, 12))
    lines = status(store, local(14, 13))
    assert lines[2] == "✅ Erinnerung gesendet (Mi 12:00)"
    assert lines[-1] == "Nächste Aktion: Entscheidung, Mi 18:00"


def test_after_a_cancellation(store: Store) -> None:
    ask(store)
    store.record_action(WEEK, Action.NUDGE, local(14, 12))
    store.record_action(WEEK, Action.CANCELLATION, local(14, 18))
    skip(store, Action.TALLY, local(16, 14))
    assert status(store, local(16, 15)) == [
        "Sonntag, 18.10.",
        "✅ Frage an die WG gesendet (Di 18:00) – 0× 👍",
        "✅ Erinnerung gesendet (Mi 12:00)",
        "❌ Absage gesendet (Mi 18:00)",
        "⏭️ Zählung: übersprungen (kein Essen)",
        "Nächste Aktion: Frage an die WG, Di 18:00",
    ]


def test_after_a_cancellation_before_tally_time(store: Store) -> None:
    ask(store)
    store.record_action(WEEK, Action.NUDGE, local(14, 12))
    store.record_action(WEEK, Action.CANCELLATION, local(14, 18))
    lines = status(store, local(14, 19))
    assert lines[4] == "– Zählung: entfällt (kein Essen)"
    # The tally on Friday won't happen; next is next week's flat ask.
    assert lines[-1] == "Nächste Aktion: Frage an die WG, Di 18:00"


def test_after_an_announcement_with_reactions(store: Store) -> None:
    ask(store, ANNA)
    skip(store, Action.NUDGE, local(14, 12))
    announce(store, ANNA, BEN, CARL)
    assert status(store, local(15, 10)) == [
        "Sonntag, 18.10.",
        "✅ Frage an die WG gesendet (Di 18:00) – 1× 👍",
        "⏭️ Erinnerung: übersprungen",
        "✅ Einladung gesendet (Mi 18:00) – 3× 👍",
        "⏳ Zählung: Fr 14:00",
        "Nächste Aktion: Zählung, Fr 14:00",
    ]


def test_after_the_tally(store: Store) -> None:
    ask(store, ANNA)
    skip(store, Action.NUDGE, local(14, 12))
    announce(store, ANNA, BEN)
    store.record_action(WEEK, Action.TALLY, local(16, 14))
    lines = status(store, local(17, 12))
    assert lines[3:] == [
        "✅ Einladung gesendet (Mi 18:00) – 2× 👍",
        "✅ Zählung gesendet (Fr 14:00)",
        "Nächste Aktion: Frage an die WG, Di 18:00",
    ]


def test_after_dinner_it_shows_the_next_week(store: Store) -> None:
    ask(store, ANNA)
    announce(store, ANNA)
    store.record_action(WEEK, Action.TALLY, local(16, 14))
    lines = status(store, local(18, 18))
    assert lines[0] == "Sonntag, 25.10."
    assert lines[1] == "⏳ Frage an die WG: Di 18:00"


def test_with_the_nudge_disabled(store: Store) -> None:
    ask(store)
    assert status(store, local(13, 20), NO_NUDGE) == [
        "Sonntag, 18.10.",
        "✅ Frage an die WG gesendet (Di 18:00) – 0× 👍",
        "– Erinnerung: aus",
        "⏳ Entscheidung: Mi 18:00",
        "⏳ Zählung: Fr 14:00",
        "Nächste Aktion: Entscheidung, Mi 18:00",
    ]


def test_a_skipped_flat_ask_skips_the_rest_of_the_week(store: Store) -> None:
    skip(store, Action.FLAT_ASK, local(14, 18))
    lines = status(store, local(14, 17))
    assert lines[1] == "⏭️ Frage an die WG: übersprungen"
    assert lines[-1] == "Nächste Aktion: Frage an die WG, Di 18:00"


def test_uses_the_effective_config(store: Store) -> None:
    moved = parse_config(
        {"templates": TEMPLATES, "schedule": {"flat_deadline": {"weekday": "thu"}}}
    )
    assert status(store, local(12, 10), moved)[3] == "⏳ Entscheidung: Do 18:00"


def test_only_reads(store: Store) -> None:
    ask(store, ANNA)
    status(store, local(13, 20))
    assert not store.has_action(WEEK, Action.NUDGE)
    assert store.overrides() == {}


def test_every_upcoming_action_has_a_german_label() -> None:
    assert {u.name for u in upcoming_actions(CONFIG, local(12, 10))} == STEP_LABELS.keys()
