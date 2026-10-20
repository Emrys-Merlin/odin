from datetime import datetime

import pytest

from odin.commands import CommandContext, handle
from odin.commands.vars import DESCRIPTIONS
from odin.config import COMMON_PLACEHOLDERS, TEMPLATE_PLACEHOLDERS, parse_config
from odin.overrides import EDITABLE_TEMPLATES, apply_overrides, schedule_key
from odin.store import Store

TEMPLATES = {
    "flat_ask": "Abendessen? {emoji} bis {deadline_day_de} {deadline}",
    "nudge": "Noch kein {emoji}",
    "cancellation": "Abgesagt.\n\nCancelled.",
    "announcement": "Essen {dinner_time}, {emoji} bis {rsvp_by}",
    "tally": "{count} mal {emoji}",
    "hello": "Hallo",
    "flat_test": "Test",
}
CONFIG = parse_config({"templates": TEMPLATES})
NOW = datetime(2026, 10, 6, 19, 0, tzinfo=CONFIG.timezone)


def make_ctx(store: Store, overrides: dict[str, str] | None = None) -> CommandContext:
    return CommandContext(
        base=CONFIG,
        config=apply_overrides(CONFIG, overrides or {}),
        store=store,
        now=NOW,
        sender="+4915100000001",
        sender_name="Anna",
    )


def vars_reply(store: Store, text: str, overrides: dict[str, str] | None = None) -> str:
    replies = handle(text, make_ctx(store, overrides))
    assert len(replies) == 1
    return replies[0]


def test_every_placeholder_has_a_description() -> None:
    shown = set().union(*(TEMPLATE_PLACEHOLDERS[name] for name in EDITABLE_TEMPLATES))
    assert shown <= DESCRIPTIONS.keys()
    # hello / flat_test are not shown, so they must not need placeholders of their own.
    assert TEMPLATE_PLACEHOLDERS["hello"] <= COMMON_PLACEHOLDERS
    assert TEMPLATE_PLACEHOLDERS["flat_test"] <= COMMON_PLACEHOLDERS
    # No stale descriptions for placeholders that no longer exist.
    assert DESCRIPTIONS.keys() <= set().union(*TEMPLATE_PLACEHOLDERS.values())


def test_vars_lists_all_placeholders_with_current_values(store: Store) -> None:
    reply = vars_reply(store, "/vars")
    lines = reply.splitlines()
    assert lines[0] == "Platzhalter für /settext:"
    for name in set().union(*(TEMPLATE_PLACEHOLDERS[t] for t in EDITABLE_TEMPLATES)):
        assert f"{{{name}}}" in reply
    assert "{emoji} – Reaktion zum Bestätigen: 👍" in lines
    assert "{deadline} – Entscheidung der WG (Uhrzeit): 18:00" in lines
    assert (
        "{deadline_day_de} / {deadline_day_en} – Entscheidung der WG (Wochentag): "
        "Mittwoch / Wednesday"
    ) in lines
    assert "{dinner_time} – Essen (Uhrzeit): 18:00" in lines
    assert (
        "{flat_ask_day_de} / {flat_ask_day_en} – Frage an die WG (Wochentag): Dienstag / Tuesday"
    ) in lines
    assert "{count} – Anzahl Zusagen auf die Ankündigung (nur in tally)" in lines
    assert lines[-2:] == [
        "{{ und }} schreiben für eine wörtliche Klammer.",
        "Nur für eine Vorlage: /vars <name>",
    ]


def test_every_line_with_a_fixed_value_shows_it(store: Store) -> None:
    reply = vars_reply(store, "!VARS")
    for value in CONFIG.placeholder_values().values():
        assert value in reply


def test_a_schedule_override_changes_the_shown_value(store: Store) -> None:
    reply = vars_reply(store, "/vars", {schedule_key("flat_deadline"): "thu 9:30"})
    assert "{deadline} – Entscheidung der WG (Uhrzeit): 09:30" in reply
    assert "Donnerstag / Thursday" in reply
    assert "Mittwoch" not in reply


def test_moving_the_flat_ask_changes_its_weekday(store: Store) -> None:
    reply = vars_reply(store, "/vars", {schedule_key("flat_ask"): "mon 18:00"})
    assert "Frage an die WG (Wochentag): Montag / Monday" in reply
    assert "Dienstag" not in reply


def test_vars_for_one_template(store: Store) -> None:
    tally = vars_reply(store, "/vars tally")
    assert tally.splitlines()[0] == "Platzhalter für tally:"
    assert "{count}" in tally
    assert "/vars <name>" not in tally

    flat_ask = vars_reply(store, "/vars Flat_Ask")
    assert flat_ask.splitlines()[0] == "Platzhalter für flat_ask:"
    assert "{count}" not in flat_ask
    assert "{emoji} – Reaktion zum Bestätigen: 👍" in flat_ask


@pytest.mark.parametrize("name", ["hello", "flat_test", "nope", "tally extra"])
def test_unknown_template(store: Store, name: str) -> None:
    reply = vars_reply(store, f"/vars {name}")
    assert reply == (
        f"Unbekannte Vorlage „{name}“. Es gibt: "
        "flat_ask, nudge, announcement, cancellation, weekday_change_cancellation, tally."
    )


def test_vars_weekday_change_cancellation_lists_its_dates(store: Store) -> None:
    lines = vars_reply(store, "/vars weekday_change_cancellation").splitlines()
    assert lines[0] == "Platzhalter für weekday_change_cancellation:"
    assert (
        "{dropped_date} – Datum des Essens, das beim Wechsel des Wochentags ausfällt "
        "(nur in weekday_change_cancellation)"
    ) in lines
    assert (
        "{first_date} – Datum des ersten Essens am neuen Wochentag "
        "(nur in weekday_change_cancellation)"
    ) in lines
    assert "{dinner_day_de} / {dinner_day_en} – Essen (Wochentag): Sonntag / Sunday" in lines
