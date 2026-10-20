import asyncio
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest

from odin.commands import CommandContext, handle
from odin.config import parse_config
from odin.engine import Account, reconcile
from odin.overrides import effective_config
from odin.signal import FakeSignalClient
from odin.store import Action, MessageKind, Outcome, Store

TEMPLATES = {
    "flat_ask": "Abendessen? {emoji} bis {deadline}",
    "nudge": "Noch kein {emoji}",
    "cancellation": "Abgesagt.\n\nCancelled.",
    "announcement": "Kochen {cook_time}, Essen {dinner_time}",
    "tally": "{count} mal {emoji}",
    "hello": "Hallo",
    "flat_test": "Test",
}
BASE = parse_config({"templates": TEMPLATES})
BERLIN = BASE.timezone
WEEK = date(2026, 10, 11)
MONDAY = datetime(2026, 10, 5, 12, 0, tzinfo=BERLIN)  # nothing sent yet this week


@pytest.fixture
def store() -> Iterator[Store]:
    with Store(":memory:") as store:
        yield store


def context(
    store: Store, now: datetime = MONDAY, sender_name: str | None = "Anna"
) -> CommandContext:
    """A context as the bot builds it: the effective config is computed from the store."""
    return CommandContext(
        base=BASE,
        config=effective_config(BASE, store, now),
        store=store,
        now=now,
        sender="+4915100000001",
        sender_name=sender_name,
    )


def run(
    store: Store, text: str, now: datetime = MONDAY, sender_name: str | None = "Anna"
) -> list[str]:
    return handle(text, context(store, now, sender_name))


def stored(store: Store) -> dict[str, str]:
    return {key: override.value for key, override in store.overrides().items()}


# --- /settext -----------------------------------------------------------------------------------


def test_settext_stores_the_text_with_sender_and_time(store: Store) -> None:
    replies = run(store, "/settext cancellation\nFällt aus.\n\nNo dinner.")
    assert replies == [
        "Gespeichert ✅ So sieht cancellation jetzt aus:",
        "Fällt aus.\n\nNo dinner.",
    ]
    override = store.overrides()["templates.cancellation"]
    assert override.value == "Fällt aus.\n\nNo dinner."
    assert override.changed_by == "Anna"
    assert override.changed_at == MONDAY.astimezone(UTC)


def test_settext_without_a_sender_name_records_the_number(store: Store) -> None:
    run(store, "/settext nudge\nHallo?", sender_name=None)
    assert store.overrides()["templates.nudge"].changed_by == "+4915100000001"


def test_settext_preview_uses_placeholders(store: Store) -> None:
    replies = run(store, "!settext flat_ask\nEssen am {dinner_day_de}? {emoji} bis {deadline}")
    assert replies[1] == "Essen am Sonntag? 👍 bis 18:00"


def test_settext_strips_surrounding_blank_lines_and_keeps_inner_whitespace(store: Store) -> None:
    text = "/settext cancellation\n\n  \nFällt aus.\n\n\n  No dinner,  sorry.\n\n  \n"
    run(store, text)
    assert stored(store) == {"templates.cancellation": "Fällt aus.\n\n\n  No dinner,  sorry."}


def test_settext_name_is_case_insensitive(store: Store) -> None:
    run(store, "/settext Cancellation\nAus.")
    assert stored(store) == {"templates.cancellation": "Aus."}


def test_settext_replaces_an_earlier_change(store: Store) -> None:
    run(store, "/settext nudge\nEins")
    run(store, "/settext nudge\nZwei")
    assert stored(store) == {"templates.nudge": "Zwei"}


def test_unknown_placeholder_is_rejected(store: Store) -> None:
    [reply] = run(store, "/settext cancellation\nAus {foo}.")
    assert reply.startswith(
        "Unbekannter Platzhalter {foo}. Welche Platzhalter es gibt, zeigt /vars cancellation."
    )
    assert "unknown placeholder {foo}" in reply  # the English detail
    assert stored(store) == {}


def test_malformed_braces_are_rejected(store: Store) -> None:
    [reply] = run(store, "/settext nudge\nKein {emoji")
    assert reply.startswith("Die geschweiften Klammern passen nicht zusammen.")
    assert "/vars nudge" in reply
    assert stored(store) == {}


def test_format_spec_is_rejected(store: Store) -> None:
    [reply] = run(store, "/settext nudge\nUm {deadline:>10}")
    assert reply.startswith("Der Platzhalter {deadline} darf kein : und kein ! enthalten.")
    assert stored(store) == {}


def test_count_is_allowed_in_tally_only(store: Store) -> None:
    [reply] = run(store, "/settext cancellation\n{count} kommen.")
    assert reply.startswith("Unbekannter Platzhalter {count}.")
    assert stored(store) == {}

    replies = run(store, "/settext tally\n{count} kommen.")
    assert replies == [
        "Gespeichert ✅ So sieht tally jetzt aus:\n(Mit der Beispielzahl 3 für {count}.)",
        "3 kommen.",
    ]
    assert stored(store) == {"templates.tally": "{count} kommen."}


def test_dropped_dates_are_allowed_in_weekday_change_cancellation_only(store: Store) -> None:
    [reply] = run(store, "/settext cancellation\n{dropped_date} fällt aus.")
    assert reply.startswith("Unbekannter Platzhalter {dropped_date}.")

    replies = run(store, "/settext weekday_change_cancellation\n{dropped_date} fällt aus.")
    assert replies == [
        "Gespeichert ✅ So sieht weekday_change_cancellation jetzt aus:\n"
        "(Mit Beispieldaten: als fiele das nächste Essen aus.)",
        "11.10. fällt aus.",
    ]
    assert stored(store) == {"templates.weekday_change_cancellation": "{dropped_date} fällt aus."}


def test_resettext_weekday_change_cancellation_falls_back_to_cancellation(store: Store) -> None:
    run(store, "/settext weekday_change_cancellation\nUmzug.")
    replies = run(store, "/resettext weekday_change_cancellation")
    assert replies[1] == "Abgesagt.\n\nCancelled."
    assert stored(store) == {}


def test_tally_preview_counts_this_weeks_confirmations(store: Store) -> None:
    message = store.track_message(WEEK, MessageKind.DINNER_ANNOUNCEMENT, "group.d=", "+49", 1)
    store.set_reaction(message, "+491", "👍", MONDAY)
    assert run(store, "/settext tally\n{count} kommen.")[1] == "1 kommen."


@pytest.mark.parametrize("name", ["hello", "flat_test", "foo", "emoji"])
def test_unknown_name(store: Store, name: str) -> None:
    [reply] = run(store, f"/settext {name}\nText")
    assert reply == (
        f"Einen Text „{name}“ gibt es nicht. Ändern lassen sich: "
        "flat_ask, nudge, announcement, cancellation, weekday_change_cancellation, tally."
    )
    assert stored(store) == {}


def test_missing_name(store: Store) -> None:
    [reply] = run(store, "/settext")
    assert reply.startswith("Welcher Text? Ändern lassen sich: flat_ask,")


@pytest.mark.parametrize("text", ["/settext nudge", "/settext nudge\n", "/settext nudge\n \n\n"])
def test_empty_text(store: Store, text: str) -> None:
    [reply] = run(store, text)
    assert reply.startswith("Der neue Text fehlt.")
    assert stored(store) == {}


def test_text_on_the_command_line(store: Store) -> None:
    [reply] = run(store, "/settext nudge Noch kein Daumen\nmehr")
    assert reply == "Der neue Text kommt in die Zeile nach /settext nudge."
    assert stored(store) == {}


def test_settext_keeps_other_overrides(store: Store) -> None:
    store.set_override("schedule.dinner", "sun 19:00", "Tim", MONDAY)
    replies = run(store, "/settext announcement\nEssen um {dinner_time}")
    assert replies[1] == "Essen um 19:00"
    assert stored(store) == {
        "schedule.dinner": "sun 19:00",
        "templates.announcement": "Essen um {dinner_time}",
    }


# --- "already sent this week" -------------------------------------------------------------------

NEXT_WEEK = "Für diese Woche ist das schon gelaufen – der Text gilt ab nächster Woche."
WEDNESDAY = datetime(2026, 10, 7, 12, 0, tzinfo=BERLIN)


def test_hint_when_this_weeks_message_was_sent(store: Store) -> None:
    store.record_action(WEEK, Action.FLAT_ASK, WEDNESDAY)
    [header, _] = run(store, "/settext flat_ask\nNeu", now=WEDNESDAY)
    assert header.splitlines() == ["Gespeichert ✅ So sieht flat_ask jetzt aus:", NEXT_WEEK]


def test_no_hint_when_another_message_was_sent(store: Store) -> None:
    store.record_action(WEEK, Action.FLAT_ASK, WEDNESDAY)
    [header, _] = run(store, "/settext nudge\nNeu", now=WEDNESDAY)
    assert NEXT_WEEK not in header


def test_no_hint_for_last_weeks_message(store: Store) -> None:
    store.record_action(date(2026, 10, 4), Action.FLAT_ASK, WEDNESDAY)
    [header, _] = run(store, "/settext flat_ask\nNeu", now=WEDNESDAY)
    assert NEXT_WEEK not in header


@pytest.mark.parametrize("name", ["announcement", "cancellation"])
@pytest.mark.parametrize("decision", [Action.ANNOUNCEMENT, Action.CANCELLATION])
def test_hint_after_either_decision(store: Store, name: str, decision: Action) -> None:
    store.record_action(WEEK, decision, WEDNESDAY)
    [header, _] = run(store, f"/settext {name}\nNeu", now=WEDNESDAY)
    assert NEXT_WEEK in header.splitlines()


def test_hint_when_this_weeks_message_was_skipped(store: Store) -> None:
    store.record_action(WEEK, Action.NUDGE, WEDNESDAY, Outcome.SKIPPED)
    [header, _] = run(store, "/settext nudge\nNeu", now=WEDNESDAY)
    assert NEXT_WEEK in header.splitlines()


def test_hint_for_tally(store: Store) -> None:
    store.record_action(WEEK, Action.TALLY, WEDNESDAY)
    [header, _] = run(store, "/settext tally\n{count}", now=WEDNESDAY)
    assert NEXT_WEEK in header.splitlines()


# --- /resettext ---------------------------------------------------------------------------------


def test_resettext_drops_the_override(store: Store) -> None:
    run(store, "/settext cancellation\nAus.")
    replies = run(store, "/resettext cancellation")
    assert replies == [
        "Zurückgesetzt auf den Standardtext ✅ So sieht cancellation jetzt aus:",
        "Abgesagt.\n\nCancelled.",
    ]
    assert stored(store) == {}


def test_resettext_keeps_other_overrides(store: Store) -> None:
    store.set_override("schedule.cook", "sun 16:00", "Tim", MONDAY)
    run(store, "/settext announcement\nNeu")
    replies = run(store, "/resettext announcement")
    assert replies[1] == "Kochen 16:00, Essen 18:00"
    assert stored(store) == {"schedule.cook": "sun 16:00"}


def test_resettext_without_override(store: Store) -> None:
    assert run(store, "/resettext nudge") == ["nudge war nicht geändert."]


def test_resettext_hint_when_already_sent(store: Store) -> None:
    run(store, "/settext flat_ask\nNeu")
    store.record_action(WEEK, Action.FLAT_ASK, WEDNESDAY)
    [header, _] = run(store, "/resettext flat_ask", now=WEDNESDAY)
    assert NEXT_WEEK in header.splitlines()


@pytest.mark.parametrize("text", ["/resettext", "/resettext hello", "/resettext nudge tally"])
def test_resettext_bad_args(store: Store, text: str) -> None:
    store.set_override("templates.nudge", "Neu", "Tim", MONDAY)
    [reply] = run(store, text)
    assert "Zurückgesetzt" not in reply
    assert stored(store) == {"templates.nudge": "Neu"}


# --- With the engine ----------------------------------------------------------------------------


def test_next_cancellation_is_sent_with_the_new_text(store: Store) -> None:
    account = Account(number="+490000000000", flat_group_id="group.f=", dinner_group_id="group.d=")
    client = FakeSignalClient(number=account.number)

    def tick(now: datetime) -> None:
        asyncio.run(reconcile(effective_config(BASE, store, now), store, client, account, now))

    tick(datetime(2026, 10, 6, 18, 0, tzinfo=BERLIN))  # flat ask
    run(store, "/settext cancellation\nFällt aus.\n\nNo dinner.", now=WEDNESDAY)
    tick(datetime(2026, 10, 7, 18, 0, tzinfo=BERLIN))  # nobody confirmed

    assert [(m.group_id, m.text) for m in client.sent[-1:]] == [
        ("group.d=", "Fällt aus.\n\nNo dinner.")
    ]
    assert store.action_outcome(WEEK, Action.CANCELLATION) is Outcome.SENT
