import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from odin.commands import CommandContext, handle
from odin.commands.core import parse
from odin.config import parse_config
from odin.cycle import TemplateName
from odin.overrides import EDITABLE_TEMPLATES, effective_config, template_key
from odin.signal import parse_event
from odin.store import MessageKind, Store

TEMPLATES = {
    "flat_ask": "Essen am {dinner_day_de}? {emoji} bis {deadline_day_de} {deadline}",
    "nudge": "Noch kein {emoji}",
    "cancellation": "Abgesagt.\n\nCancelled.",
    "announcement": "Kochen {cook_time}, Essen {dinner_time}.\n\n{emoji} bis {rsvp_by_day_de}",
    "tally": "{count} mal {emoji}",
    "hello": "Hallo",
    "flat_test": "Test",
}
CONFIG = parse_config({"templates": TEMPLATES})
NOW = datetime(2026, 10, 8, 10, 0, tzinfo=CONFIG.timezone)  # Thu; dinner week of Sun 11 Oct
WEEK = date(2026, 10, 11)
FIXTURES = Path(__file__).parent / "fixtures" / "signal"


def context(store: Store) -> CommandContext:
    return CommandContext(
        base=CONFIG,
        config=effective_config(CONFIG, store, NOW),
        store=store,
        now=NOW,
        sender="+4915100000002",
        sender_name="Anna",
    )


def override(store: Store, name: TemplateName, text: str) -> None:
    # 22:30 UTC on 11 Oct is 12 Oct in Berlin.
    store.set_override(template_key(name), text, "Tim", datetime(2026, 10, 11, 22, 30, tzinfo=UTC))


# --- /texts -------------------------------------------------------------------------------------


def test_texts(store: Store) -> None:
    assert handle("/texts", context(store)) == [
        "Texte:\n"
        "flat_ask (WG-Gruppe) – Frage, ob das Essen stattfindet\n"
        "nudge (WG-Gruppe) – Erinnerung, wenn noch niemand bestätigt hat\n"
        "announcement (Essensgruppe) – Ankündigung mit Bitte um Rückmeldung\n"
        "cancellation (Essensgruppe) – Absage\n"
        "weekday_change_cancellation (Essensgruppe) – Absage beim Wechsel des Wochentags "
        "(nicht gesetzt, es gilt cancellation)\n"
        "tally (WG-Gruppe) – Anzahl der Zusagen zum Bestellen\n"
        "introduction (Essensgruppe) – Vorstellung von Odin, per /introduce (nicht gesetzt)\n"
        "\n"
        "Anzeigen: /text <name>"
    ]


def test_texts_marks_overrides(store: Store) -> None:
    override(store, TemplateName.NUDGE, "Bitte {emoji}!")
    [reply] = handle("!TEXTS", context(store))
    lines = reply.splitlines()
    assert "nudge (WG-Gruppe) – Erinnerung, wenn noch niemand bestätigt hat ✏️ 12.10. von Tim" in (
        lines
    )
    assert sum("✏️" in line for line in lines) == 1


def test_texts_lists_only_the_editable_templates(store: Store) -> None:
    [reply] = handle("/texts", context(store))
    listed = [line.split()[0] for line in reply.splitlines()[1:8]]
    assert listed == list(EDITABLE_TEMPLATES)
    assert "hello" not in reply
    assert "flat_test" not in reply


# --- /text <name> -------------------------------------------------------------------------------


def test_text_announcement(store: Store) -> None:
    raw, preview = handle("/text announcement", context(store))
    assert raw == "/settext announcement\n" + TEMPLATES["announcement"]
    assert preview == ("Vorschau (diese Woche):\nKochen 17:00, Essen 18:00.\n\n👍 bis Freitag")


def test_text_name_is_case_insensitive(store: Store) -> None:
    raw, _ = handle("/text Announcement", context(store))
    assert raw.startswith("/settext announcement\n")


def test_text_shows_the_override(store: Store) -> None:
    override(store, TemplateName.FLAT_ASK, "Wer ist {dinner_day_de} da? {emoji}")
    raw, preview = handle("/text flat_ask", context(store))
    assert raw == "/settext flat_ask\nWer ist {dinner_day_de} da? {emoji}"
    assert preview == "Vorschau (diese Woche): ✏️ 12.10. von Tim\nWer ist Sonntag da? 👍"


def test_raw_reply_is_a_valid_settext_command(store: Store) -> None:
    raw, _ = handle("/text cancellation", context(store))
    invocation = parse(raw)
    assert invocation is not None
    assert invocation.name == "settext"
    assert invocation.args == "cancellation\n" + TEMPLATES["cancellation"]


def test_raw_reply_sent_by_odin_does_not_come_back_as_a_command(store: Store) -> None:
    # ODIN sees its own sends only as sync messages, which parse to no event at all.
    raw, _ = handle("/text announcement", context(store))
    data = json.loads((FIXTURES / "sync_message_jsonrpc.json").read_text())
    data["params"]["envelope"]["syncMessage"]["sentMessage"]["message"] = raw
    assert parse_event(json.dumps(data)) is None


def test_text_tally_without_announcement(store: Store) -> None:
    raw, preview = handle("/text tally", context(store))
    assert raw == "/settext tally\n{count} mal {emoji}"
    assert preview == ("Vorschau (diese Woche, noch keine Ankündigung – Beispielzahl 3):\n3 mal 👍")


def test_text_tally_with_announcement(store: Store) -> None:
    message = store.track_message(WEEK, MessageKind.DINNER_ANNOUNCEMENT, "g", "+491", 1000)
    for reactor in ("+492", "+493"):
        store.set_reaction(message, reactor, "👍", NOW)
    _, preview = handle("/text tally", context(store))
    assert preview == "Vorschau (diese Woche, aktuelle Zahl der Zusagen):\n2 mal 👍"


@pytest.mark.parametrize("text", ["/text bogus", "/text hello", "/text flat_test"])
def test_text_unknown_name(store: Store, text: str) -> None:
    name = text.split()[1]
    assert handle(text, context(store)) == [
        f"Unbekannter Text „{name}“. Möglich: "
        "flat_ask, nudge, announcement, cancellation, weekday_change_cancellation, tally, "
        "introduction"
    ]


def test_text_without_name(store: Store) -> None:
    assert handle("/text", context(store)) == [
        "Welcher Text? Möglich: "
        "flat_ask, nudge, announcement, cancellation, weekday_change_cancellation, tally, "
        "introduction\n"
        "Z. B. /text announcement"
    ]


# --- weekday_change_cancellation (#85) ----------------------------------------------------------

MOVED = "Ab jetzt {dinner_day_de}, {dropped_date} fällt aus, ab {first_date}"


def test_text_weekday_change_cancellation_falls_back_to_cancellation(store: Store) -> None:
    raw, preview = handle("/text weekday_change_cancellation", context(store))
    assert raw == "/settext weekday_change_cancellation\n" + TEMPLATES["cancellation"]
    assert preview == (
        "Vorschau (Beispiel: als fiele das nächste Essen aus) "
        "(nicht gesetzt, es gilt cancellation):\nAbgesagt.\n\nCancelled."
    )


def test_text_weekday_change_cancellation_with_sample_dates(store: Store) -> None:
    override(store, TemplateName.WEEKDAY_CHANGE_CANCELLATION, MOVED)
    [listing] = handle("/texts", context(store))
    assert (
        "weekday_change_cancellation (Essensgruppe) – Absage beim Wechsel des Wochentags "
        "✏️ 12.10. von Tim"
    ) in listing.splitlines()
    raw, preview = handle("/text weekday_change_cancellation", context(store))
    assert raw == "/settext weekday_change_cancellation\n" + MOVED
    assert preview == (
        "Vorschau (Beispiel: als fiele das nächste Essen aus): ✏️ 12.10. von Tim\n"
        "Ab jetzt Sonntag, 11.10. fällt aus, ab 18.10."
    )


def test_text_weekday_change_cancellation_of_a_dropped_week(store: Store) -> None:
    override(store, TemplateName.WEEKDAY_CHANGE_CANCELLATION, MOVED)
    store.record_dropped_week(WEEK, NOW)
    _, preview = handle("/text weekday_change_cancellation", context(store))
    assert preview == (
        "Vorschau (diese Woche): ✏️ 12.10. von Tim\nAb jetzt Sonntag, 11.10. fällt aus, ab 18.10."
    )
