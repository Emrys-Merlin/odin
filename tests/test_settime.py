import asyncio
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from typing import Any

import pytest

from odin.commands import CommandContext, handle
from odin.commands.settime import (
    ASK_ALREADY_SENT,
    FROM_NEXT_WEEK,
    NUDGE_USAGE,
    RESET,
    SAVED,
    SETTIME_USAGE,
    THIS_WEEK,
    parse_weekly_time,
)
from odin.config import Config, WeeklyTime, parse_config
from odin.engine import Account, reconcile
from odin.overrides import NUDGE_ENABLED_KEY, effective_config
from odin.reactions import handle_reaction
from odin.signal import FakeSignalClient, ReactionEvent
from odin.store import Action, MessageKind, Outcome, Store

TEMPLATES = {
    "flat_ask": "Essen am {dinner_day_de}? {emoji} bis {deadline_day_de} {deadline}",
    "nudge": "Noch kein {emoji}",
    "cancellation": "Abgesagt.\n\nCancelled.",
    "announcement": "Essen {dinner_time}, {emoji} bis {rsvp_by}",
    "tally": "{count} mal {emoji}",
    "hello": "Hallo",
    "flat_test": "Test",
}


def make_config(**data: Any) -> Config:
    return parse_config({"templates": TEMPLATES, **data})


CONFIG = make_config()
NO_NUDGE = make_config(schedule={"nudge": {"enabled": False}})
BERLIN = CONFIG.timezone
# Default schedule; the week whose dinner is on Sunday 2026-10-11:
# flat ask Tue 6. 18:00, nudge Wed 7. 12:00, deadline Wed 7. 18:00, tally Fri 9. 14:00,
# dinner Sun 11. 18:00.
WEEK = date(2026, 10, 11)


def local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=BERLIN)


@pytest.fixture
def store() -> Iterator[Store]:
    with Store(":memory:") as store:
        yield store


def send(store: Store, text: str, now: datetime, base: Config = CONFIG) -> str:
    """Handle `text` as Anna at `now` with the effective config; the one reply."""
    ctx = CommandContext(
        base=base,
        config=effective_config(base, store, now),
        store=store,
        now=now,
        sender="+4915100000001",
        sender_name="Anna",
    )
    replies = handle(text, ctx)
    assert len(replies) == 1
    return replies[0]


def values(store: Store) -> dict[str, str]:
    return {key: override.value for key, override in store.overrides().items()}


DECIDED = (Action.FLAT_ASK, Action.NUDGE, Action.ANNOUNCEMENT)


def record(store: Store, *actions: Action, at: datetime) -> None:
    for action in actions:
        store.record_action(WEEK, action, at)


# --- /settime: parsing and storing --------------------------------------------------------------


def test_valid_change_is_stored(store: Store) -> None:
    reply = send(store, "/settime flat_deadline thu 12:00", local(5, 10))

    assert values(store) == {"schedule.flat_deadline": "thu 12:00"}
    assert store.overrides()["schedule.flat_deadline"].changed_by == "Anna"
    assert reply.splitlines()[:3] == [
        SAVED,
        "Frist für die WG / Entscheidung (flat_deadline): Do 12:00, "
        "nächstes Mal Do 08.10. um 12:00",
        THIS_WEEK,
    ]
    assert "Achtung" not in reply


def test_changed_by_falls_back_to_the_number(store: Store) -> None:
    ctx = CommandContext(
        base=CONFIG,
        config=CONFIG,
        store=store,
        now=local(5, 10),
        sender="+4915100000001",
        sender_name=None,
    )
    handle("!settime tally sat 10:00", ctx)
    assert store.overrides()["schedule.tally"].changed_by == "+4915100000001"


@pytest.mark.parametrize("day", ["thu", "thursday", "THU", "Thu", "Thursday", "THURSDAY"])
def test_weekday_forms(store: Store, day: str) -> None:
    send(store, f"/settime flat_deadline {day} 12:00", local(5, 10))
    assert values(store) == {"schedule.flat_deadline": "thu 12:00"}


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        ("mon 9:05", WeeklyTime(0, time(9, 5))),
        ("tue 18:00", WeeklyTime(1, time(18))),
        ("wed 6:00", WeeklyTime(2, time(6))),
        ("Thu 0:00", WeeklyTime(3, time(0))),
        ("fri 23:59", WeeklyTime(4, time(23, 59))),
        ("SAT 10:00", WeeklyTime(5, time(10))),
        ("Monday 07:00", WeeklyTime(0, time(7))),
        ("wednesday 7:00", WeeklyTime(2, time(7))),
        ("sunday 7:00", WeeklyTime(6, time(7))),
        ("sun 7:00", WeeklyTime(6, time(7))),
        ("Tuesday 7:00", WeeklyTime(1, time(7))),
    ],
)
def test_parse_weekly_time(words: str, expected: WeeklyTime) -> None:
    assert parse_weekly_time(*words.split()) == expected


def test_short_time_is_stored_zero_padded(store: Store) -> None:
    send(store, "/settime tally sat 9:05", local(5, 10))
    assert values(store) == {"schedule.tally": "sat 09:05"}


@pytest.mark.parametrize("clock", ["25:00", "12:60", "12", "12:5", "1200", "12:00h", "-1:00"])
def test_bad_time(store: Store, clock: str) -> None:
    reply = send(store, f"/settime tally sat {clock}", local(5, 10))
    assert reply.startswith("Die Uhrzeit")
    assert clock in reply
    assert values(store) == {}


@pytest.mark.parametrize("day", ["xy", "mont", "d", "samstagabend", "do", "donnerstag", "sa"])
def test_bad_weekday(store: Store, day: str) -> None:
    reply = send(store, f"/settime tally {day} 10:00", local(5, 10))
    assert reply.startswith(f"Den Wochentag {day} kenne ich nicht")
    assert values(store) == {}


def test_unknown_point(store: Store) -> None:
    reply = send(store, "/settime lunch sat 10:00", local(5, 10))
    assert reply.startswith("Den Zeitpunkt lunch kenne ich nicht")
    assert values(store) == {}


@pytest.mark.parametrize("args", ["", "tally", "tally sat", "tally sat 10:00 extra"])
def test_settime_usage(store: Store, args: str) -> None:
    assert send(store, f"/settime {args}", local(5, 10)) == SETTIME_USAGE


def test_point_is_case_insensitive(store: Store) -> None:
    send(store, "/settime TALLY sat 10:00", local(5, 10))
    assert values(store) == {"schedule.tally": "sat 10:00"}


# --- Guard 1: schedule order --------------------------------------------------------------------


def test_order_violation(store: Store) -> None:
    reply = send(store, "/settime tally wed 10:00", local(5, 10))
    assert reply.startswith("Das passt nicht: flat_deadline muss vor tally liegen.")
    assert "flat_ask → nudge → flat_deadline → tally → dinner" in reply
    assert values(store) == {}


def test_order_takes_the_other_overrides_into_account(store: Store) -> None:
    send(store, "/settime flat_deadline thu 18:00", local(5, 10))
    reply = send(store, "/settime tally thu 12:00", local(5, 10))
    assert reply.startswith("Das passt nicht")
    assert values(store) == {"schedule.flat_deadline": "thu 18:00"}


def test_nudge_on_rejected_when_its_time_breaks_the_order(store: Store) -> None:
    # The nudge keeps its Wed 12:00 while off; the deadline moves before it.
    send(store, "/nudge off", local(5, 10))
    send(store, "/settime flat_deadline wed 10:00", local(5, 10))
    reply = send(store, "/nudge on", local(5, 10))
    assert reply.startswith("Das passt nicht: nudge muss vor flat_deadline liegen.")
    assert values(store)[NUDGE_ENABLED_KEY] == "false"


# --- Guard 2: the dinner week -------------------------------------------------------------------


def test_moving_dinner_so_the_week_flips_is_rejected(store: Store) -> None:
    # Sunday 18:30: this week's dinner has started, so it is already next week (18.10.).
    # Dinner at 19:00 would put now back into this week.
    reply = send(store, "/settime dinner sun 19:00", local(11, 18, 30))
    assert reply.startswith("Damit würde sich die aktuelle Essenswoche verschieben")
    assert "18.10. → 11.10." in reply
    assert values(store) == {}


def test_moving_dinner_before_now_is_rejected(store: Store) -> None:
    # Sunday 17:30: dinner at 17:00 would already have started.
    base = make_config(schedule={"cook": {"weekday": "sun", "time": "16:00"}})
    reply = send(store, "/settime dinner sun 17:00", local(11, 17, 30), base=base)
    assert reply.startswith("Damit würde sich die aktuelle Essenswoche verschieben")
    assert values(store) == {}


def test_moving_dinner_within_the_week_is_fine(store: Store) -> None:
    reply = send(store, "/settime dinner sun 19:00", local(10, 19))
    assert reply.startswith(SAVED)
    assert values(store) == {"schedule.dinner": "sun 19:00"}


# --- Guard 3: steps becoming due right now ------------------------------------------------------


def test_deadline_moved_before_now_is_rejected(store: Store) -> None:
    # The issue's example; the nudge is off, else Tue 18:30 would break the order first.
    record(store, Action.FLAT_ASK, at=local(6, 18))
    reply = send(store, "/settime flat_deadline tue 18:30", local(6, 19), base=NO_NUDGE)
    assert reply == "Dann wäre die Entscheidung sofort fällig – das geht nicht über den Chat."
    assert values(store) == {}


def test_deadline_moved_before_now_with_nudge_breaks_the_order(store: Store) -> None:
    record(store, Action.FLAT_ASK, at=local(6, 18))
    reply = send(store, "/settime flat_deadline tue 18:30", local(6, 19))
    assert reply.startswith("Das passt nicht: nudge muss vor flat_deadline liegen.")


def test_deadline_moved_to_thursday_is_accepted_with_a_warning(store: Store) -> None:
    record(store, Action.FLAT_ASK, at=local(6, 18))
    reply = send(store, "/settime flat_deadline thu 18:00", local(6, 19), base=NO_NUDGE)
    assert reply.startswith(SAVED)
    assert THIS_WEEK in reply
    assert ASK_ALREADY_SENT.format(old="Mi 18:00", new="Do 18:00") in reply
    assert values(store) == {"schedule.flat_deadline": "thu 18:00"}


def test_no_sent_warning_before_the_ask(store: Store) -> None:
    reply = send(store, "/settime flat_deadline thu 18:00", local(6, 10))
    assert "Achtung" not in reply


def test_no_sent_warning_once_decided(store: Store) -> None:
    record(store, Action.FLAT_ASK, Action.NUDGE, Action.ANNOUNCEMENT, at=local(7, 18))
    reply = send(store, "/settime flat_deadline thu 18:00", local(8, 10))
    assert reply.splitlines() == [
        SAVED,
        "Frist für die WG / Entscheidung (flat_deadline): Do 18:00, "
        "nächstes Mal Do 15.10. um 18:00",
        FROM_NEXT_WEEK,
    ]


def test_announcement_already_sent_warning(store: Store) -> None:
    record(store, Action.FLAT_ASK, Action.NUDGE, Action.ANNOUNCEMENT, at=local(7, 18))
    reply = send(store, "/settime cook sun 16:00", local(8, 10))
    assert reply.splitlines()[2:] == [
        THIS_WEEK,
        "Achtung: Die Ankündigung ist diese Woche schon raus und nennt noch die alte Zeit für "
        "cook (So 17:00). Sag am besten in der Essensgruppe Bescheid, dass jetzt So 16:00 gilt.",
    ]


def test_no_announcement_warning_after_a_cancellation(store: Store) -> None:
    record(store, Action.FLAT_ASK, Action.NUDGE, Action.CANCELLATION, at=local(7, 18))
    reply = send(store, "/settime cook sun 16:00", local(8, 10))
    assert "Achtung" not in reply


def test_no_sent_warning_when_the_ask_was_skipped(store: Store) -> None:
    store.record_action(WEEK, Action.FLAT_ASK, local(6, 18), Outcome.SKIPPED)
    reply = send(store, "/settime flat_deadline thu 18:00", local(6, 19))
    assert "Achtung" not in reply


@pytest.mark.parametrize(
    ("now", "recorded", "command", "step"),
    [
        # Monday: moving the flat ask before now would send it at once.
        (local(5, 10), (), "/settime flat_ask mon 09:00", "die Frage an die WG"),
        (local(5, 10), (), "/settime flat_ask sun 20:00", "die Frage an die WG"),
        # Wednesday 13:00, nudge sent: the deadline moved to before now.
        (local(7, 13), (Action.FLAT_ASK, Action.NUDGE), "/settime flat_deadline wed 12:30", None),
        # Thursday, decided: the tally moved before now.
        (
            local(8, 12),
            (Action.FLAT_ASK, Action.NUDGE, Action.ANNOUNCEMENT),
            "/settime tally thu 11:00",
            "die Zählung",
        ),
        # Wednesday 11:00 before the nudge: the nudge moved before now.
        (local(7, 11), (Action.FLAT_ASK,), "/settime nudge wed 10:00", "die Erinnerung"),
    ],
)
def test_newly_due_steps_are_rejected(
    store: Store, now: datetime, recorded: tuple[Action, ...], command: str, step: str | None
) -> None:
    record(store, *recorded, at=now - timedelta(hours=1))
    reply = send(store, command, now)
    if step is None:
        assert reply == "Dann wäre die Entscheidung sofort fällig – das geht nicht über den Chat."
    else:
        assert reply == f"Dann wäre {step} sofort fällig – das geht nicht über den Chat."
    assert values(store) == {}


@pytest.mark.parametrize(
    ("now", "recorded", "command"),
    [
        # Moving a step that is already done, to before now.
        (local(6, 19), (Action.FLAT_ASK,), "/settime flat_ask mon 18:00"),
        (local(7, 13), (Action.FLAT_ASK, Action.NUDGE), "/settime nudge wed 09:00"),
        (
            local(10, 10),
            (Action.FLAT_ASK, Action.NUDGE, Action.ANNOUNCEMENT, Action.TALLY),
            "/settime tally thu 10:00",
        ),
        # Moving a future step later or to another future time.
        (local(5, 10), (), "/settime flat_ask mon 12:00"),
        (
            local(8, 12),
            (Action.FLAT_ASK, Action.NUDGE, Action.ANNOUNCEMENT),
            "/settime tally sat 10:00",
        ),
        # Points that are no steps of their own.
        (
            local(10, 10),
            (Action.FLAT_ASK, Action.NUDGE, Action.ANNOUNCEMENT),
            "/settime cook sat 12:00",
        ),
        (
            local(10, 10),
            (Action.FLAT_ASK, Action.NUDGE, Action.ANNOUNCEMENT),
            "/settime rsvp_by thu 12:00",
        ),
    ],
)
def test_harmless_changes_are_accepted(
    store: Store, now: datetime, recorded: tuple[Action, ...], command: str
) -> None:
    record(store, *recorded, at=now - timedelta(hours=1))
    reply = send(store, command, now)
    assert reply.startswith(SAVED), reply


def test_nudge_on_within_its_window_is_rejected(store: Store) -> None:
    record(store, Action.FLAT_ASK, at=local(6, 18))
    reply = send(store, "/nudge on", local(7, 13), base=NO_NUDGE)
    assert reply == "Dann wäre die Erinnerung sofort fällig – das geht nicht über den Chat."
    assert values(store) == {}


def test_nudge_on_after_the_deadline_is_accepted(store: Store) -> None:
    # The nudge would only be recorded as skipped, nothing is sent.
    record(store, Action.FLAT_ASK, Action.ANNOUNCEMENT, at=local(7, 18))
    reply = send(store, "/nudge on", local(8, 10), base=NO_NUDGE)
    assert reply.startswith(SAVED)
    assert values(store) == {NUDGE_ENABLED_KEY: "true"}


def test_reset_goes_through_the_guard(store: Store) -> None:
    # Deadline moved to Thursday; on Wednesday 19:00 resetting it would make the decision due.
    record(store, Action.FLAT_ASK, Action.NUDGE, at=local(7, 12))
    send(store, "/settime flat_deadline thu 18:00", local(6, 19))
    reply = send(store, "/resettime flat_deadline", local(7, 19))
    assert reply == "Dann wäre die Entscheidung sofort fällig – das geht nicht über den Chat."
    assert values(store) == {"schedule.flat_deadline": "thu 18:00"}


# --- /nudge and /resettime ----------------------------------------------------------------------


@pytest.mark.parametrize(("word", "value"), [("off", "false"), ("OFF", "false"), ("on", "true")])
def test_nudge_words(store: Store, word: str, value: str) -> None:
    send(store, f"/nudge {word}", local(5, 10))
    assert values(store) == {NUDGE_ENABLED_KEY: value}


@pytest.mark.parametrize("args", ["", "vielleicht", "on off", "an", "aus"])
def test_nudge_usage(store: Store, args: str) -> None:
    assert send(store, f"/nudge {args}", local(5, 10)) == NUDGE_USAGE


def test_nudge_off_then_reset(store: Store) -> None:
    reply = send(store, "/nudge off", local(5, 10))
    assert reply.splitlines()[:3] == [SAVED, "Erinnerung an die WG (nudge): aus", THIS_WEEK]
    assert effective_config(CONFIG, store, local(5, 10)).schedule.nudge is None

    send(store, "/settime nudge wed 10:00", local(5, 10))
    assert values(store) == {NUDGE_ENABLED_KEY: "false", "schedule.nudge": "wed 10:00"}

    reply = send(store, "/resettime nudge", local(5, 10))
    assert reply.splitlines()[:2] == [
        RESET,
        "Erinnerung an die WG (nudge): Mi 12:00, nächstes Mal Mi 07.10. um 12:00",
    ]
    assert values(store) == {}
    assert (
        effective_config(CONFIG, store, local(5, 10)).schedule.nudge == CONFIG.schedule.nudge_time
    )


def test_reset_when_nothing_is_overridden(store: Store) -> None:
    reply = send(store, "/resettime tally", local(5, 10))
    assert reply == "Zählung der Gäste (tally) war nicht geändert – steht auf Fr 14:00."
    reply = send(store, "/resettime nudge", local(5, 10))
    assert reply == "Die Erinnerung war nicht geändert – sie ist an, Mi 12:00."


def test_reset(store: Store) -> None:
    send(store, "/settime tally sat 10:00", local(5, 10))
    send(store, "/settime cook sun 16:00", local(5, 10))
    reply = send(store, "/resettime tally", local(5, 10))
    assert reply.splitlines()[:2] == [
        RESET,
        "Zählung der Gäste (tally): Fr 14:00, nächstes Mal Fr 09.10. um 14:00",
    ]
    assert values(store) == {"schedule.cook": "sun 16:00"}


def test_next_occurrence_is_next_week_once_passed(store: Store) -> None:
    record(store, Action.FLAT_ASK, Action.NUDGE, Action.ANNOUNCEMENT, Action.TALLY, at=local(9, 14))
    reply = send(store, "/settime tally sat 10:00", local(10, 12))
    assert "nächstes Mal Sa 17.10. um 10:00" in reply
    assert FROM_NEXT_WEEK in reply


# --- Hard-coded weekday warning -----------------------------------------------------------------


def test_hardcoded_weekday_warning(store: Store) -> None:
    store.set_override("templates.nudge", "Bis Mittwoch {deadline}!", "Tim", local(5, 9))
    reply = send(store, "/settime tally sat 10:00", local(5, 10))
    assert reply.splitlines()[-1] == (
        "Achtung: Die Vorlage nudge nennt einen Wochentag fest – prüfe sie mit /text nudge."
    )


def test_hardcoded_weekday_warning_in_the_toml(store: Store) -> None:
    base = parse_config(
        {"templates": TEMPLATES | {"cancellation": "Kein Essen.\n\nNo dinner this Sunday."}}
    )
    reply = send(store, "/settime tally sat 10:00", local(5, 10), base=base)
    assert "Die Vorlage cancellation nennt einen Wochentag fest" in reply


def test_no_warning_for_weekday_placeholders(store: Store) -> None:
    reply = send(store, "/settime tally sat 10:00", local(5, 10))
    assert "Vorlage" not in reply


# --- The engine follows the change --------------------------------------------------------------

ACCOUNT = Account(number="+490000000000", flat_group_id="group.flat=", dinner_group_id="group.d=")


def test_engine_sends_the_tally_at_the_new_time(store: Store) -> None:
    send(store, "/settime tally sat 10:00", local(5, 10))
    client = FakeSignalClient(number=ACCOUNT.number)
    sent_at: dict[str, datetime] = {}

    def tick(now: datetime) -> None:
        config = effective_config(CONFIG, store, now)
        before = len(client.sent)
        asyncio.run(reconcile(config, store, client, ACCOUNT, now))
        for message in client.sent[before:]:
            sent_at[message.text] = now

    now = local(6, 17)
    while now < local(11, 17):
        tick(now)
        poll = store.tracked_message(WEEK, MessageKind.FLAT_POLL)
        if poll is not None and not store.reactions_for(poll):
            event = ReactionEvent(
                emoji="👍",
                reactor="+4915100000002",
                target_author=poll.author,
                target_timestamp=poll.timestamp,
                group_id=poll.group_id,
                is_remove=False,
                timestamp=int(now.timestamp() * 1000),
            )
            handle_reaction(event, store, effective_config(CONFIG, store, now), now)
        now += timedelta(minutes=30)

    assert store.action_outcome(WEEK, Action.ANNOUNCEMENT) is Outcome.SENT
    assert sent_at["0 mal 👍"] == local(10, 10)
    assert store.action_time(WEEK, Action.TALLY) == local(10, 10)
