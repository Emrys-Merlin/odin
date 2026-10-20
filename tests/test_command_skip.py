"""/skip and /unskip end to end: the commands, the skip dates in the store, the engine, /status."""

import asyncio
from collections.abc import Iterator
from datetime import date, datetime, timedelta

import pytest

from odin.clock import FixedClock
from odin.commands import CommandContext, TrackedReply, handle
from odin.commands.cancel import SKIP_DATE
from odin.commands.skip import (
    ALREADY_SKIPPED,
    DROPPED_WEEK,
    NO_SUCH_DATE,
    NOT_A_DINNER_DAY,
    NOT_SKIPPED,
    PAST,
    TOO_LATE,
    UNSKIP_USAGE,
    USAGE,
)
from odin.config import Config, parse_config
from odin.engine import Account, reconcile
from odin.events import consume_events
from odin.overrides import effective_config
from odin.signal import FakeSignalClient, GroupMessage
from odin.store import Action, Outcome, Store

TEMPLATES = {
    "flat_ask": "ASK {emoji} bis {deadline}",
    "nudge": "NUDGE {deadline}",
    "cancellation": "ABGESAGT {dinner_day_de}\n\nCANCELLED {dinner_day_en}",
    "announcement": "ESSEN {dinner_time}\n\nDINNER {dinner_time}",
    "tally": "TALLY {count} x {emoji}",
    "hello": "HELLO",
    "flat_test": "TEST",
}
# Default schedule: ask Tue 18:00, nudge Wed 12:00, decision Wed 18:00, tally Fri 14:00,
# dinner Sun 18:00.
CONFIG = parse_config({"templates": TEMPLATES})
# For a Sunday → Saturday dinner, cooking has to move off Sunday first.
SAT_COOK = parse_config({"templates": TEMPLATES, "schedule": {"cook": {"weekday": "sat"}}})
BERLIN = CONFIG.timezone

BOT = "+490000000000"
FLAT, DINNER = "group.flat=", "group.dinner="
ACCOUNT = Account(number=BOT, flat_group_id=FLAT, dinner_group_id=DINNER)
ANNA = "+4915100000001"

# Monday 05.10. is in the dinner week of Sunday 11.10.
WEEK = date(2026, 10, 11)
NEXT = date(2026, 10, 18)
XMAS = date(2026, 12, 27)
CANCELLATION = "ABGESAGT Sonntag\n\nCANCELLED Sunday"


def local(day: int, hour: int, minute: int = 0, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=BERLIN)


def ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


@pytest.fixture
def store() -> Iterator[Store]:
    with Store(":memory:") as s:
        yield s


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


def tick(store: Store, client: FakeSignalClient, start: datetime, end: datetime) -> None:
    now = start
    while now < end:
        asyncio.run(reconcile(CONFIG, store, client, ACCOUNT, now))
        now += timedelta(minutes=15)


def texts(client: FakeSignalClient, group: str) -> list[str]:
    return [sent.text for sent in client.sent if sent.group_id == group]


def outcomes(store: Store, week: date) -> dict[Action, Outcome]:
    found = {action: store.action_outcome(week, action) for action in Action}
    return {action: outcome for action, outcome in found.items() if outcome is not None}


# --- /skip --------------------------------------------------------------------------------------


def test_skip_stores_the_day_and_shows_the_cancellation(store: Store) -> None:
    assert run_command(store, "/skip 2026-12-27", local(5, 10)) == [
        "Eingetragen: Am Sonntag, 27.12.2026 gibt es kein Essen. Ich frage die WG in der Woche "
        "nicht und schicke der Essensgruppe am Mi 23.12. 18:00 diese Absage:"
        f"\n\n{CANCELLATION}\n\n/unskip 2026-12-27 nimmt das zurück."
    ]
    [skip] = store.skip_dates()
    assert (skip.day, skip.added_by, skip.added_at) == (XMAS, "Anna", local(5, 10))


def test_skip_of_this_week_before_its_flat_ask_is_a_skip_date(store: Store) -> None:
    [reply] = run_command(store, "!SKIP 2026-10-11", local(6, 17))
    assert not isinstance(reply, TrackedReply)
    assert reply.startswith("Eingetragen: Am Sonntag, 11.10.2026 gibt es kein Essen.")
    assert store.skip_date(WEEK) is not None


def test_skip_of_this_week_after_its_flat_ask_is_cancel(store: Store) -> None:
    store.record_action(WEEK, Action.FLAT_ASK, local(6, 18))
    [skip] = run_command(store, "/skip 2026-10-11", local(6, 20))
    [cancel] = run_command(store, "/cancel", local(6, 20))
    assert isinstance(skip, TrackedReply)
    assert isinstance(cancel, TrackedReply)
    assert (skip, skip.week, skip.kind) == (cancel, cancel.week, cancel.kind)
    assert store.skip_dates() == []


def test_skip_of_this_week_after_its_cancellation_is_refused_as_by_cancel(store: Store) -> None:
    store.record_action(WEEK, Action.FLAT_ASK, local(6, 18))
    store.record_action(WEEK, Action.CANCELLATION, local(7, 18))
    assert run_command(store, "/skip 2026-10-11", local(8, 10)) == run_command(
        store, "/cancel", local(8, 10)
    )


@pytest.mark.parametrize("args", ["27.12.2026", "2026-12-27 2027-01-03", "dec 27", "2026-1-3"])
def test_skip_with_a_bad_argument_shows_the_usage(store: Store, args: str) -> None:
    assert run_command(store, f"/skip {args}", local(5, 10)) == [USAGE]


def test_skip_of_a_date_that_does_not_exist(store: Store) -> None:
    assert run_command(store, "/skip 2026-02-30", local(5, 10)) == [
        NO_SUCH_DATE.format(date="2026-02-30")
    ]


def test_skip_of_a_past_dinner_is_refused(store: Store) -> None:
    assert run_command(store, "/skip 2026-10-11", local(11, 18)) == [
        PAST.format(day="Sonntag, 11.10.2026")
    ]


def test_skip_of_a_day_without_dinner_is_refused(store: Store) -> None:
    assert run_command(store, "/skip 2026-12-26", local(5, 10)) == [
        NOT_A_DINNER_DAY.format(day="Samstag, 26.12.2026", weekdays="sonntags")
    ]
    assert store.skip_dates() == []


def test_skip_twice_is_refused(store: Store) -> None:
    run_command(store, "/skip 2026-12-27", local(5, 10))
    assert run_command(store, "/skip 2026-12-27", local(6, 10)) == [
        ALREADY_SKIPPED.format(day="Sonntag, 27.12.2026", marker="✏️ 05.10. von Anna")
    ]


def test_skip_follows_a_pending_dinner_weekday_change(store: Store) -> None:
    store.record_action(WEEK, Action.FLAT_ASK, local(6, 18))  # the running week has started
    run_command(store, "/settime dinner sat 18:00", local(7, 10), SAT_COOK)
    # Before the switch the weeks are still Sunday ones, after it Saturday ones.
    assert run_command(store, "/skip 2026-10-18", local(7, 11), SAT_COOK) == [
        NOT_A_DINNER_DAY.format(day="Sonntag, 18.10.2026", weekdays="samstags")
    ]
    [reply] = run_command(store, "/skip 2026-10-24", local(7, 11), SAT_COOK)
    assert reply.startswith(
        "Eingetragen: Am Samstag, 24.10.2026 gibt es kein Essen. Ich frage die WG in der Woche "
        "nicht und schicke der Essensgruppe am Mi 21.10. 18:00 diese Absage:\n\nABGESAGT Samstag"
    )


def test_skip_of_a_week_dropped_by_a_pending_weekday_change_is_refused(store: Store) -> None:
    # Sunday → Monday: the Monday right after the switch is dropped.
    store.record_action(WEEK, Action.FLAT_ASK, local(6, 18))
    run_command(store, "/settime dinner mon 18:00", local(7, 10))
    assert run_command(store, "/skip 2026-10-12", local(7, 11)) == [
        DROPPED_WEEK.format(day="Montag, 12.10.2026")
    ]


# --- /skip without a date: the list ------------------------------------------------------------


def test_list_when_empty(store: Store) -> None:
    assert run_command(store, "/skip", local(5, 10)) == [
        "Es sind keine Tage ohne Essen eingetragen.\n"
        "Eintragen: /skip JJJJ-MM-TT · Zurücknehmen: /unskip JJJJ-MM-TT"
    ]


def test_list_shows_upcoming_skip_dates_in_order(store: Store) -> None:
    store.add_skip_date(date(2026, 10, 4), "Ben", local(1, 9))  # over: not listed
    store.add_skip_date(XMAS, "Anna", local(2, 9))
    store.add_skip_date(WEEK, "+4915100000002", local(3, 9))
    assert run_command(store, "/skip", local(5, 10)) == [
        "Kein Essen an diesen Tagen:\n"
        "• So 11.10.2026 ✏️ 03.10. von +4915100000002\n"
        "• So 27.12.2026 ✏️ 02.10. von Anna\n"
        "\n"
        "Eintragen: /skip JJJJ-MM-TT · Zurücknehmen: /unskip JJJJ-MM-TT"
    ]


def test_list_marks_a_skip_date_that_is_no_dinner_day_any_more(store: Store) -> None:
    store.add_skip_date(XMAS, "Anna", local(2, 9))
    sat = parse_config(
        {
            "templates": TEMPLATES,
            "schedule": {"cook": {"weekday": "sat"}, "dinner": {"weekday": "sat"}},
        }
    )
    [reply] = run_command(store, "/skip", local(5, 10), sat)
    assert "• So 27.12.2026 (kein Essenstag mehr) ✏️ 02.10. von Anna" in reply.splitlines()


# --- /unskip ------------------------------------------------------------------------------------


def test_unskip_takes_a_skip_date_back(store: Store) -> None:
    run_command(store, "/skip 2026-12-27", local(5, 10))
    assert run_command(store, "/unskip 2026-12-27", local(6, 10)) == [
        "Zurückgenommen: Am Sonntag, 27.12.2026 gibt es wieder Essen wie immer."
    ]
    assert store.skip_dates() == []


def test_unskip_of_a_day_that_is_not_skipped(store: Store) -> None:
    assert run_command(store, "/unskip 2026-12-27", local(5, 10)) == [
        NOT_SKIPPED.format(day="Sonntag, 27.12.2026")
    ]


@pytest.mark.parametrize("args", ["", "27.12.2026"])
def test_unskip_with_a_bad_argument_shows_the_usage(store: Store, args: str) -> None:
    assert run_command(store, f"/unskip {args}", local(5, 10)) == [UNSKIP_USAGE]


def test_unskip_of_a_past_skip_date_is_refused(store: Store) -> None:
    store.add_skip_date(date(2026, 10, 4), "Anna", local(1, 9))
    assert run_command(store, "/unskip 2026-10-04", local(5, 10)) == [
        PAST.format(day="Sonntag, 04.10.2026")
    ]


def test_unskip_once_the_flat_ask_was_skipped_is_refused(store: Store) -> None:
    store.add_skip_date(WEEK, "Anna", local(1, 9))
    tick(store, FakeSignalClient(number=BOT), local(6, 18), local(6, 18, 15))
    assert run_command(store, "/unskip 2026-10-11", local(6, 19)) == [
        TOO_LATE.format(day="Sonntag, 11.10.2026")
    ]
    assert store.skip_date(WEEK) is not None


def test_listed_in_help(store: Store) -> None:
    [reply] = run_command(store, "/help", local(5, 10))
    lines = reply.splitlines()
    assert (
        "/skip [JJJJ-MM-TT] – Trägt einen Tag ohne Essen im Voraus ein; ohne Datum: zeigt die "
        "Liste." in lines
    )
    assert "/unskip <JJJJ-MM-TT> – Nimmt einen mit /skip eingetragenen Tag zurück." in lines


# --- The engine ---------------------------------------------------------------------------------


def test_a_skip_date_cancels_at_the_decision_time_without_asking(store: Store) -> None:
    store.add_skip_date(WEEK, "Anna", local(1, 9))
    client = FakeSignalClient(number=BOT)
    tick(store, client, local(5, 0), local(7, 18))
    assert texts(client, DINNER) == []
    assert outcomes(store, WEEK) == {
        Action.FLAT_ASK: Outcome.SKIPPED,
        Action.NUDGE: Outcome.SKIPPED,
    }

    tick(store, client, local(7, 18), local(13, 18, 15))
    assert texts(client, DINNER) == [CANCELLATION]
    assert store.action_time(WEEK, Action.CANCELLATION) == local(7, 18)
    assert outcomes(store, WEEK) == {
        Action.FLAT_ASK: Outcome.SKIPPED,
        Action.NUDGE: Outcome.SKIPPED,
        Action.CANCELLATION: Outcome.SENT,
        Action.TALLY: Outcome.SKIPPED,
    }
    # Nothing went to the flat group; the next week is asked as usual.
    assert texts(client, FLAT) == ["ASK 👍 bis 18:00"]
    assert store.action_outcome(NEXT, Action.FLAT_ASK) is Outcome.SENT


def test_the_flat_ask_is_only_skipped_at_its_time(store: Store) -> None:
    store.add_skip_date(WEEK, "Anna", local(1, 9))
    client = FakeSignalClient(number=BOT)
    tick(store, client, local(5, 0), local(6, 18))
    assert outcomes(store, WEEK) == {}
    run_command(store, "/unskip 2026-10-11", local(6, 17))
    tick(store, client, local(6, 18), local(6, 18, 15))
    assert texts(client, FLAT) == ["ASK 👍 bis 18:00"]


def test_a_late_skip_date_cancellation_is_skipped_like_any_late_step(store: Store) -> None:
    store.add_skip_date(WEEK, "Anna", local(1, 9))
    client = FakeSignalClient(number=BOT)
    tick(store, client, local(11, 18), local(11, 18, 15))  # down until dinner started
    assert texts(client, DINNER) == []
    assert store.action_outcome(WEEK, Action.CANCELLATION) is Outcome.SKIPPED


def test_cancel_in_a_skip_date_week_is_refused(store: Store) -> None:
    store.add_skip_date(WEEK, "Anna", local(1, 9))
    assert run_command(store, "/cancel", local(6, 19)) == [
        SKIP_DATE.format(day="Sonntag, 11.10.", at="Mi 07.10. 18:00")
    ]


def test_skip_through_the_event_consumer(store: Store) -> None:
    """/skip through the event consumer, as in the running bot."""
    client = FakeSignalClient(number=BOT)
    now = local(5, 10)
    event = GroupMessage(
        sender=ANNA, sender_name="Anna", text="/skip 2026-10-11", group_id=FLAT, timestamp=ms(now)
    )
    client.inject(event)
    client.close()
    asyncio.run(consume_events(client, store, CONFIG, ACCOUNT, FixedClock(now)))
    [reply] = texts(client, FLAT)
    assert reply.startswith("Eingetragen: Am Sonntag, 11.10.2026 gibt es kein Essen.")
    assert store.skip_date(WEEK) is not None


# --- /status ------------------------------------------------------------------------------------


def status(store: Store, now: datetime) -> list[str]:
    [reply] = run_command(store, "/status", now)
    return reply.splitlines()


def test_status_of_a_skip_date_week(store: Store) -> None:
    store.add_skip_date(WEEK, "Anna", local(1, 9))
    store.add_skip_date(XMAS, "Anna", local(1, 9))
    assert status(store, local(5, 10)) == [
        "Sonntag, 11.10.",
        "– Frage an die WG: entfällt (per /skip)",
        "– Erinnerung: entfällt (per /skip)",
        "⏳ Absage an die Essensgruppe: Mi 18:00 – per /skip",
        "– Zählung: entfällt (kein Essen)",
        "Kein Essen per /skip: So 27.12.2026",
        "Nächste Aktion: Absage an die Essensgruppe, Mi 18:00",
    ]
    tick(store, FakeSignalClient(number=BOT), local(6, 18), local(7, 18, 15))
    assert status(store, local(8, 10)) == [
        "Sonntag, 11.10.",
        "⏭️ Frage an die WG: übersprungen",
        "⏭️ Erinnerung: übersprungen",
        "❌ Absage gesendet (Mi 18:00) – per /skip",
        "– Zählung: entfällt (kein Essen)",
        "Kein Essen per /skip: So 27.12.2026",
        "Nächste Aktion: Frage an die WG, Di 18:00",
    ]


def test_status_next_action_when_next_week_is_a_skip_date(store: Store) -> None:
    store.add_skip_date(NEXT, "Anna", local(1, 9))
    store.record_action(WEEK, Action.FLAT_ASK, local(6, 18))
    store.record_action(WEEK, Action.NUDGE, local(7, 12), Outcome.SKIPPED)
    store.record_action(WEEK, Action.CANCELLATION, local(7, 18))
    store.record_action(WEEK, Action.TALLY, local(9, 14), Outcome.SKIPPED)
    lines = status(store, local(10, 10))
    assert lines[-2:] == [
        "Kein Essen per /skip: So 18.10.2026",
        "Nächste Aktion: Absage an die Essensgruppe, Mi 18:00",
    ]
