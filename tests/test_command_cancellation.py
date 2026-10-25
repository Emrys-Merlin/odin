"""/cancellation on|off|reset and `decision.cancellation`: the cancellation switched off."""

import asyncio
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from helpers import local, ms

from odin.commands import CommandContext, handle
from odin.commands import cancel as cancel_command
from odin.commands import cancellation as cancellation_command
from odin.commands import hiatus as hiatus_command
from odin.commands.ui import FROM_NEXT_WEEK, RESET, SAVED, THIS_WEEK
from odin.config import Config, ConfigError, parse_config
from odin.engine import Account, reconcile
from odin.overrides import CANCELLATION_ENABLED_KEY, effective_config
from odin.reactions import handle_reaction
from odin.signal import FakeSignalClient, ReactionEvent
from odin.store import Action, MessageKind, Outcome, Store

TEMPLATES = {
    "flat_ask": "ASK {emoji} bis {deadline}",
    "nudge": "NUDGE {deadline}",
    "cancellation": "ABGESAGT {dinner_day_de}\n\nCANCELLED {dinner_day_en}",
    "announcement": "ESSEN {dinner_time}\n\nDINNER {dinner_time}",
    "tally": "TALLY {count} x {emoji}",
    "hello": "HELLO",
    "flat_test": "TEST",
}
WEEKDAY_CHANGE = "UMZUG {dropped_date}\n\nMOVE {first_date}"
HIATUS = "PAUSE\n\nBREAK"


def make_config(cancellation: bool = True, **templates: str) -> Config:
    return parse_config(
        {"templates": TEMPLATES | templates, "decision": {"cancellation": cancellation}}
    )


CONFIG = make_config()
OFF = make_config(cancellation=False)

BOT = "+490000000000"
FLAT, DINNER = "group.flat=", "group.dinner="
ACCOUNT = Account(number=BOT, flat_group_id=FLAT, dinner_group_id=DINNER)
ANNA, BEN = "+4915100000001", "+4915100000002"

# Default schedule: ask Tue 06.10. 18:00, nudge Wed 12:00, decision Wed 07.10. 18:00,
# tally Fri 14:00, dinner Sun 11.10. 18:00.
WEEK = date(2026, 10, 11)
NEXT = WEEK + timedelta(weeks=1)
CANCELLATION = "ABGESAGT Sonntag\n\nCANCELLED Sunday"


def run_command(store: Store, text: str, now: datetime, base: Config = CONFIG) -> list[str]:
    ctx = CommandContext(
        base=base,
        config=effective_config(base, store, now),
        store=store,
        now=now,
        sender=ANNA,
        sender_name="Anna",
    )
    return handle(text, ctx)


def tick(store: Store, client: FakeSignalClient, config: Config, start: datetime, end: datetime):
    """Tick every 15 minutes from `start` until before `end`, with the effective config."""
    now = start
    while now < end:
        effective = effective_config(config, store, now)
        asyncio.run(reconcile(effective, store, client, ACCOUNT, now))
        now += timedelta(minutes=15)


def react(store: Store, kind: MessageKind, now: datetime, week: date = WEEK) -> None:
    message = store.tracked_message(week, kind)
    assert message is not None, f"{kind} not tracked"
    event = ReactionEvent(
        emoji="👍",
        reactor=BEN,
        target_author=message.author,
        target_timestamp=message.timestamp,
        group_id=message.group_id,
        is_remove=False,
        timestamp=ms(now),
    )
    handle_reaction(event, store, CONFIG, now)


def texts(client: FakeSignalClient, group: str) -> list[str]:
    return [sent.text for sent in client.sent if sent.group_id == group]


def outcomes(store: Store, week: date = WEEK) -> dict[Action, Outcome]:
    found = {action: store.action_outcome(week, action) for action in Action}
    return {action: outcome for action, outcome in found.items() if outcome is not None}


@pytest.fixture
def client() -> FakeSignalClient:
    return FakeSignalClient(number=BOT)


# --- Config -------------------------------------------------------------------------------------


def test_the_cancellation_is_on_by_default() -> None:
    assert parse_config({"templates": TEMPLATES}).decision.cancellation
    assert not OFF.decision.cancellation


@pytest.mark.parametrize(
    ("decision", "message"),
    [
        ({"cancellation": "no"}, "decision.cancellation: must be true or false"),
        ({"cancel": False}, "decision: unknown key"),
    ],
)
def test_bad_decision_section(decision: dict[str, Any], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_config({"templates": TEMPLATES, "decision": decision})


# --- /cancellation ------------------------------------------------------------------------------


def test_off_stores_the_override_and_applies_this_week(store: Store) -> None:
    [reply] = run_command(store, "/cancellation off", local(5, 10))
    assert reply.split("\n") == [
        SAVED,
        "Absage an die Essensgruppe (cancellation): aus",
        cancellation_command.OFF_NOTE.format(emoji="👍"),
        THIS_WEEK,
    ]
    override = store.overrides()[CANCELLATION_ENABLED_KEY]
    assert (override.value, override.changed_by) == ("false", "Anna")
    assert not effective_config(CONFIG, store, local(5, 10)).decision.cancellation


def test_on_overrides_the_config_file(store: Store) -> None:
    [reply] = run_command(store, "/Cancellation ON", local(5, 10), base=OFF)
    assert reply.split("\n") == [SAVED, "Absage an die Essensgruppe (cancellation): an", THIS_WEEK]
    assert effective_config(OFF, store, local(5, 10)).decision.cancellation


def test_after_the_decision_it_applies_from_next_week(store: Store) -> None:
    store.record_action(WEEK, Action.CANCELLATION, local(7, 18))
    [reply] = run_command(store, "/cancellation off", local(8, 10))
    assert reply.endswith(FROM_NEXT_WEEK)


def test_reset_goes_back_to_the_config_file(store: Store) -> None:
    run_command(store, "/cancellation on", local(5, 10), base=OFF)
    [reply] = run_command(store, "/cancellation reset", local(5, 11), base=OFF)
    assert reply.split("\n")[:2] == [RESET, "Absage an die Essensgruppe (cancellation): aus"]
    assert CANCELLATION_ENABLED_KEY not in store.overrides()


def test_reset_without_an_override(store: Store) -> None:
    assert run_command(store, "/cancellation reset", local(5, 10)) == [
        "Die Absage an die Essensgruppe war nicht geändert – sie ist an."
    ]


@pytest.mark.parametrize("args", ["", "maybe", "off now"])
def test_bad_arguments_show_the_usage(store: Store, args: str) -> None:
    assert run_command(store, f"/cancellation {args}", local(5, 10)) == [cancellation_command.USAGE]
    assert store.overrides() == {}


def test_listed_in_help(store: Store) -> None:
    [reply] = run_command(store, "/help", local(5, 10))
    assert "/cancellation on|off|reset – Schaltet die Absage an die Essensgruppe" in reply


# --- The engine ---------------------------------------------------------------------------------


def test_off_no_confirmation_cancels_silently(store: Store, client: FakeSignalClient) -> None:
    tick(store, client, OFF, local(5, 0), local(13, 19))
    assert texts(client, DINNER) == []
    assert outcomes(store) == {
        Action.FLAT_ASK: Outcome.SENT,
        Action.NUDGE: Outcome.SENT,
        Action.CANCELLATION: Outcome.SILENCED,
        Action.TALLY: Outcome.SKIPPED,
    }
    assert store.action_time(WEEK, Action.CANCELLATION) == local(7, 18)
    # The next week runs as usual.
    assert store.action_outcome(NEXT, Action.FLAT_ASK) is Outcome.SENT


def test_off_a_confirmed_dinner_is_still_announced(store: Store, client: FakeSignalClient) -> None:
    tick(store, client, OFF, local(5, 0), local(6, 19))
    react(store, MessageKind.FLAT_POLL, local(6, 19))
    tick(store, client, OFF, local(6, 19), local(11, 0))
    assert texts(client, DINNER) == ["ESSEN 18:00\n\nDINNER 18:00"]
    assert outcomes(store)[Action.TALLY] is Outcome.SENT


def test_switched_off_in_the_running_week(store: Store, client: FakeSignalClient) -> None:
    tick(store, client, CONFIG, local(5, 0), local(7, 13))
    run_command(store, "/cancellation off", local(7, 13))
    tick(store, client, CONFIG, local(7, 13), local(8, 0))
    assert texts(client, DINNER) == []
    assert outcomes(store)[Action.CANCELLATION] is Outcome.SILENCED
    # Switched on after the decision: the week stays as it is.
    run_command(store, "/cancellation on", local(8, 0))
    tick(store, client, CONFIG, local(8, 0), local(9, 0))
    assert texts(client, DINNER) == []


def test_a_late_tick_is_still_silenced(store: Store, client: FakeSignalClient) -> None:
    tick(store, client, OFF, local(5, 0), local(7, 17))
    tick(store, client, OFF, local(8, 9), local(8, 10))  # down over the decision
    assert outcomes(store)[Action.CANCELLATION] is Outcome.SILENCED
    assert store.action_time(WEEK, Action.CANCELLATION) == local(8, 9)


def test_off_a_skip_date_cancels_silently(store: Store, client: FakeSignalClient) -> None:
    store.add_skip_date(WEEK, "Anna", local(1, 9))
    tick(store, client, OFF, local(5, 0), local(12, 0))
    assert client.sent == []
    assert outcomes(store) == {
        Action.FLAT_ASK: Outcome.SKIPPED,
        Action.NUDGE: Outcome.SKIPPED,
        Action.CANCELLATION: Outcome.SILENCED,
        Action.TALLY: Outcome.SKIPPED,
    }


def test_off_cancel_still_posts(store: Store, client: FakeSignalClient) -> None:
    tick(store, client, OFF, local(5, 0), local(6, 19))
    react(store, MessageKind.FLAT_POLL, local(6, 19))
    tick(store, client, OFF, local(6, 19), local(8, 9))
    [request] = run_command(store, "/cancel", local(8, 9), base=OFF)
    store.track_message(WEEK, MessageKind.CANCEL_REQUEST, FLAT, BOT, ms(local(8, 9)))
    react(store, MessageKind.CANCEL_REQUEST, local(8, 10))
    tick(store, client, OFF, local(8, 10), local(8, 11))
    assert texts(client, DINNER) == ["ESSEN 18:00\n\nDINNER 18:00", CANCELLATION]
    assert outcomes(store)[Action.CANCELLATION] is Outcome.SENT
    assert CANCELLATION in request


@pytest.mark.parametrize(
    ("config", "sent", "outcome"),
    [
        (OFF, [], Outcome.SILENCED),
        (
            make_config(cancellation=False, weekday_change_cancellation=WEEKDAY_CHANGE),
            ["UMZUG 11.10.\n\nMOVE 18.10."],
            Outcome.SENT,
        ),
    ],
    ids=["fallback", "own-template"],
)
def test_off_a_dropped_week(
    store: Store, client: FakeSignalClient, config: Config, sent: list[str], outcome: Outcome
) -> None:
    store.record_dropped_week(WEEK, local(9, 10))
    tick(store, client, config, local(9, 10), local(9, 11))
    assert texts(client, DINNER) == sent
    assert outcomes(store)[Action.CANCELLATION] is outcome


def hiatus(store: Store, now: datetime, config: Config) -> None:
    """/hiatus at `now`, confirmed a minute later."""
    run_command(store, "/hiatus", now, base=config)
    store.track_message(WEEK, MessageKind.HIATUS_REQUEST, FLAT, BOT, ms(now))
    react(store, MessageKind.HIATUS_REQUEST, now + timedelta(minutes=1))


@pytest.mark.parametrize(
    ("config", "sent", "notice"),
    [
        (OFF, [], Outcome.SILENCED),
        (make_config(cancellation=False, hiatus=HIATUS), [HIATUS], Outcome.SENT),
    ],
    ids=["fallback", "own-template"],
)
def test_off_the_hiatus_notice(
    store: Store, client: FakeSignalClient, config: Config, sent: list[str], notice: Outcome
) -> None:
    hiatus(store, local(5, 10), config)
    tick(store, client, config, local(5, 11), local(12, 0))
    assert texts(client, DINNER) == sent
    active = store.active_hiatus()
    assert active is not None
    assert active.notice is notice


def test_off_a_hiatus_after_the_flat_ask_still_cancels(
    store: Store, client: FakeSignalClient
) -> None:
    tick(store, client, OFF, local(5, 0), local(7, 10))
    hiatus(store, local(7, 10), OFF)
    tick(store, client, OFF, local(7, 11), local(7, 12))
    assert texts(client, DINNER) == [CANCELLATION]
    active = store.active_hiatus()
    assert active is not None
    assert active.notice is Outcome.SKIPPED  # it would only repeat the cancellation


# --- Other commands -----------------------------------------------------------------------------


def test_cancel_after_a_silenced_cancellation_is_refused(store: Store) -> None:
    store.record_action(WEEK, Action.FLAT_ASK, local(6, 18))
    store.record_action(WEEK, Action.CANCELLATION, local(7, 18), Outcome.SILENCED)
    assert run_command(store, "/cancel", local(8, 10), base=OFF) == [
        cancel_command.CANCELLATION_SILENCED.format(day="Sonntag, 11.10.")
    ]


def test_hiatus_says_the_dinner_group_gets_nothing(store: Store) -> None:
    [reply] = run_command(store, "/hiatus", local(5, 10), base=OFF)
    assert reply.endswith(hiatus_command.NOTHING_SILENCED)
    assert "ABGESAGT" not in reply


def status(store: Store, now: datetime, base: Config = OFF) -> list[str]:
    [reply] = run_command(store, "/status", now, base=base)
    return reply.splitlines()


def test_status_while_off(store: Store, client: FakeSignalClient) -> None:
    assert status(store, local(5, 10))[3] == (
        "⏳ Entscheidung: Mi 18:00 (Absage an die Essensgruppe: aus)"
    )
    tick(store, client, OFF, local(6, 18), local(7, 18, 15))
    assert status(store, local(8, 10)) == [
        "Sonntag, 11.10.",
        "✅ Frage an die WG gesendet (Di 18:00) – 0× 👍",
        "✅ Erinnerung gesendet (Mi 12:00)",
        "– Absage an die Essensgruppe: nicht gesendet (aus)",
        "– Zählung: entfällt (kein Essen)",
        "Nächste Aktion: Frage an die WG, Di 18:00",
    ]


def test_status_of_a_skip_date_while_off(store: Store, client: FakeSignalClient) -> None:
    store.add_skip_date(WEEK, "Anna", local(1, 9))
    lines = status(store, local(5, 10))
    assert lines[3] == "– Absage an die Essensgruppe: aus – per /skip"
    assert lines[-1] == "Nächste Aktion: Frage an die WG, Di 18:00"  # of the next week
    tick(store, client, OFF, local(6, 18), local(7, 18, 15))
    assert status(store, local(8, 10))[3] == (
        "– Absage an die Essensgruppe: nicht gesendet (aus) – per /skip"
    )


def test_status_of_a_silenced_hiatus_notice(store: Store, client: FakeSignalClient) -> None:
    hiatus(store, local(5, 10), OFF)
    tick(store, client, OFF, local(5, 11), local(5, 12))
    assert "– Hinweis an die Essensgruppe: nicht gesendet (Absage ist aus)" in status(
        store, local(5, 13)
    )


def test_schedule_marks_the_decision(store: Store) -> None:
    run_command(store, "/cancellation off", local(5, 10))
    [reply] = run_command(store, "/schedule", local(5, 11))
    assert (
        "flat_deadline – Entscheidung: Mi 18:00 (ohne Absage an die Essensgruppe) ✏️ 05.10. von Anna"
    ) in reply.split("\n")


def test_skip_while_off_promises_no_cancellation(store: Store) -> None:
    [reply] = run_command(store, "/skip 2026-12-27", local(5, 10), base=OFF)
    assert reply == (
        "Eingetragen: Am Sonntag, 27.12.2026 gibt es kein Essen. Ich frage die WG in der Woche "
        "nicht. Die Absage an die Essensgruppe ist aus (/cancellation) – ist sie am "
        "Mi 23.12. 18:00 noch aus, bekommt die Essensgruppe nichts.\n\n"
        "/unskip 2026-12-27 nimmt das zurück."
    )


def test_off_cancel_in_a_skip_date_week_posts_the_cancellation(
    store: Store, client: FakeSignalClient
) -> None:
    store.add_skip_date(WEEK, "Anna", local(1, 9))
    [request] = run_command(store, "/cancel", local(5, 10), base=OFF)
    assert request.endswith(CANCELLATION)
    store.track_message(WEEK, MessageKind.CANCEL_REQUEST, FLAT, BOT, ms(local(5, 10)))
    react(store, MessageKind.CANCEL_REQUEST, local(5, 11))
    tick(store, client, OFF, local(5, 11), local(12, 0))
    assert texts(client, DINNER) == [CANCELLATION]
    assert outcomes(store)[Action.CANCELLATION] is Outcome.SENT


def test_off_cancel_in_a_dropped_week_is_allowed(store: Store) -> None:
    store.record_dropped_week(WEEK, local(9, 10))
    [request] = run_command(store, "/cancel", local(9, 10), base=OFF)
    assert request.endswith(CANCELLATION)
    with_text = make_config(cancellation=False, weekday_change_cancellation=WEEKDAY_CHANGE)
    assert run_command(store, "/cancel", local(9, 10), base=with_text) == [
        cancel_command.DROPPED_WEEK.format(day="Sonntag, 11.10.")
    ]


def test_new_dinner_weekday_while_off_says_the_dropped_week_gets_nothing(store: Store) -> None:
    [reply] = run_command(store, "/settime dinner mon 18:00", local(15, 12), base=OFF)
    assert reply.splitlines()[-1] == (
        "Die Absage an die Essensgruppe ist aus (/cancellation) – für den Mo 19.10. schicke ich "
        "ihr nichts."
    )
