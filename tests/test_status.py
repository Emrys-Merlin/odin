from datetime import date, datetime

import pytest
from helpers import local

from odin.commands import CommandContext, handle
from odin.commands.status import STEP_LABELS
from odin.config import Config, parse_config
from odin.engine import upcoming_actions
from odin.overrides import effective_config
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
# For a Sunday → Saturday dinner, cooking has to move off Sunday first.
SAT_COOK = parse_config({"templates": TEMPLATES, "schedule": {"cook": {"weekday": "sat"}}})

# Dinner on Sunday 2026-10-18; flat ask on Tuesday 2026-10-13.
WEEK = date(2026, 10, 18)
MON_19 = date(2026, 10, 19)
BOT = "+490000000000"
FLAT, DINNER = "group.flat=", "group.dinner="
ANNA, BEN, CARL = "+4915100000001", "+4915100000002", "+4915100000003"


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


def test_an_untracked_flat_poll(store: Store) -> None:
    store.record_action(WEEK, Action.FLAT_ASK, ASK_TIME)  # sent, but its response was unreadable
    lines = status(store, local(13, 20))
    assert lines[1] == "✅ Frage an die WG gesendet (Di 18:00) – 👍 nicht zählbar"
    assert lines[-1] == "Nächste Aktion: Erinnerung, Mi 12:00 (nur falls noch kein 👍)"


def test_a_flat_poll_asked_again(store: Store) -> None:
    store.record_action(WEEK, Action.FLAT_ASK, ASK_TIME)
    store.record_action(WEEK, Action.FLAT_ASK_RETRY, local(13, 18, 15))
    retry = store.track_message(WEEK, MessageKind.FLAT_POLL, FLAT, BOT, 1_001)
    store.set_reaction(retry, ANNA, "👍", local(13, 19))
    lines = status(store, local(13, 20))
    assert lines[1] == "✅ Frage an die WG gesendet (Di 18:00), nochmal gefragt (Di 18:15) – 1× 👍"
    assert lines[-1] == "Nächste Aktion: Entscheidung, Mi 18:00"


def test_an_untracked_announcement(store: Store) -> None:
    ask(store, ANNA)
    skip(store, Action.NUDGE, local(14, 12))
    store.record_action(WEEK, Action.ANNOUNCEMENT, local(14, 18))
    store.record_action(WEEK, Action.ANNOUNCEMENT_NOTICE, local(14, 18))
    assert status(store, local(15, 10))[3] == "✅ Einladung gesendet (Mi 18:00) – 👍 nicht zählbar"


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


# --- A pending dinner weekday change (#77) -------------------------------------------------------


def chat(store: Store, text: str, now: datetime, base: Config = CONFIG) -> list[str]:
    """`text` as sent in the flat group at `now`, with the overrides stored at `now` applied."""
    ctx = CommandContext(
        base=base,
        config=effective_config(base, store, now),
        store=store,
        now=now,
        sender=ANNA,
        sender_name="Anna",
    )
    return handle(text, ctx)[0].splitlines()


def a_full_week(store: Store) -> None:
    ask(store, ANNA)
    skip(store, Action.NUDGE, local(14, 12))
    announce(store, ANNA, BEN)


def test_no_pending_change_for_a_new_time_on_the_same_weekday(store: Store) -> None:
    a_full_week(store)
    chat(store, "/settime dinner sun 19:00", local(15, 9))
    assert chat(store, "/status", local(15, 10)) == [
        "Sonntag, 18.10.",
        "✅ Frage an die WG gesendet (Di 18:00) – 1× 👍",
        "⏭️ Erinnerung: übersprungen",
        "✅ Einladung gesendet (Mi 18:00) – 2× 👍",
        "⏳ Zählung: Fr 14:00",
        "Nächste Aktion: Zählung, Fr 14:00",
    ]


def test_a_pending_sun_to_sat_change(store: Store) -> None:
    a_full_week(store)
    chat(store, "/settime dinner sat 18:00", local(15, 9), SAT_COOK)
    assert chat(store, "/status", local(15, 10), SAT_COOK) == [
        "Sonntag, 18.10.",
        "✅ Frage an die WG gesendet (Di 18:00) – 1× 👍",
        "⏭️ Erinnerung: übersprungen",
        "✅ Einladung gesendet (Mi 18:00) – 2× 👍",
        "⏳ Zählung: Fr 14:00",
        "Ab Sa 24.10. ist das Essen samstags um 18:00.",
        "Nächste Aktion: Zählung, Fr 14:00",
    ]


def test_a_pending_sun_to_mon_change_with_a_dropped_week(store: Store) -> None:
    a_full_week(store)
    chat(store, "/settime dinner mon 19:30", local(15, 9))
    lines = chat(store, "/status", local(15, 10))
    assert lines[-2:] == [
        "Ab Mo 26.10. ist das Essen montags um 19:30 (Mo 19.10. entfällt).",
        "Nächste Aktion: Zählung, Fr 14:00",
    ]


@pytest.mark.parametrize(("base", "change"), [(SAT_COOK, "sat 18:00"), (CONFIG, "mon 18:00")])
def test_next_action_just_before_the_switch(store: Store, base: Config, change: str) -> None:
    a_full_week(store)
    chat(store, f"/settime dinner {change}", local(15, 9), base)
    store.record_action(WEEK, Action.TALLY, local(16, 14))
    lines = chat(store, "/status", local(18, 17, 59), base)
    assert lines[0] == "Sonntag, 18.10."
    # The new schedule's first step: the flat ask on Tue 20.10. (for Sat 24. or Mon 26.).
    assert lines[-1] == "Nächste Aktion: Frage an die WG, Di 18:00"


def test_next_action_just_after_the_switch(store: Store) -> None:
    a_full_week(store)
    chat(store, "/settime dinner sat 18:00", local(15, 9), SAT_COOK)
    store.record_action(WEEK, Action.TALLY, local(16, 14))
    lines = chat(store, "/status", local(18, 18), SAT_COOK)
    assert lines[0] == "Samstag, 24.10."
    assert "Ab" not in "\n".join(lines)  # no longer pending
    assert lines[-1] == "Nächste Aktion: Frage an die WG, Di 18:00"


def test_next_action_just_after_the_switch_skips_the_dropped_week(store: Store) -> None:
    a_full_week(store)
    chat(store, "/settime dinner mon 18:00", local(15, 9))
    store.record_action(WEEK, Action.TALLY, local(16, 14))
    # Before the engine's next tick has recorded the dropped week's steps as skipped.
    lines = chat(store, "/status", local(18, 18))
    assert lines[0] == "Montag, 19.10."
    assert lines[-1] == "Nächste Aktion: Frage an die WG, Di 18:00"
    # And once it has.
    for action in (Action.FLAT_ASK, Action.NUDGE, Action.CANCELLATION, Action.TALLY):
        store.record_action(MON_19, action, local(18, 18, 1), Outcome.SKIPPED)
    lines = chat(store, "/status", local(18, 18, 2))
    assert lines[1:] == [
        "⏭️ Frage an die WG: übersprungen",
        "⏭️ Erinnerung: übersprungen",
        "⏭️ Entscheidung: übersprungen",
        "⏭️ Zählung: übersprungen (kein Essen)",
        "Nächste Aktion: Frage an die WG, Di 18:00",
    ]


def test_a_flat_ask_past_its_window_skips_the_rest_of_the_week(store: Store) -> None:
    # The bot was down over the whole flat ask window: the engine will skip the week.
    assert status(store, local(14, 19))[-1] == "Nächste Aktion: Frage an die WG, Di 18:00"
