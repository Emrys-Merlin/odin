"""/hiatus and /resume end to end: the commands, the confirming reaction and the engine."""

import asyncio
from datetime import date, datetime, timedelta

import pytest
from helpers import local, ms

from odin.clock import FixedClock
from odin.commands import CommandContext, TrackedReply, handle
from odin.commands import cancel as cancel_command
from odin.commands import hiatus as hiatus_command
from odin.commands.status import status
from odin.config import Config, parse_config
from odin.engine import Account, SendFailure, reconcile
from odin.events import consume_events
from odin.health import untracked_warnings
from odin.signal import FakeSignalClient, GroupMessage, ReactionEvent, SignalApiError
from odin.store import Action, MessageKind, Outcome, Store

TEMPLATES = {
    "flat_ask": "ASK {emoji} bis {deadline}",
    "nudge": "NUDGE {deadline}",
    "cancellation": "ABGESAGT {dinner_day_de}\n\nCANCELLED {dinner_day_en}",
    "announcement": "ESSEN {dinner_time}\n\nDINNER {dinner_time}",
    "tally": "TALLY {count} x {emoji}",
    "hiatus": "PAUSE ab {dinner_day_de}\n\nBREAK from {dinner_day_en}",
    "hello": "HELLO",
    "flat_test": "TEST",
}
# Default schedule: ask Tue 18:00, nudge Wed 12:00, decision Wed 18:00, tally Fri 14:00,
# dinner Sun 18:00.
CONFIG = parse_config({"templates": TEMPLATES})
# A config written before the hiatus template existed: the notice falls back to the cancellation.
NO_HIATUS_TEXT = parse_config({"templates": {k: v for k, v in TEMPLATES.items() if k != "hiatus"}})

BOT = "+490000000000"
FLAT, DINNER = "group.flat=", "group.dinner="
ACCOUNT = Account(number=BOT, flat_group_id=FLAT, dinner_group_id=DINNER)
ANNA, BEN = "+4915100000001", "+4915100000002"

WEEK = date(2026, 10, 11)  # flat ask Tue 06.10. 18:00, decision Wed 07.10. 18:00
NEXT = WEEK + timedelta(weeks=1)  # flat ask Tue 13.10. 18:00
AFTER = WEEK + timedelta(weeks=2)  # flat ask Tue 20.10. 18:00
CANCELLATION = "ABGESAGT Sonntag\n\nCANCELLED Sunday"
ANNOUNCEMENT = "ESSEN 18:00\n\nDINNER 18:00"
NOTICE = "PAUSE ab Sonntag\n\nBREAK from Sunday"


class Client(FakeSignalClient):
    """Sent messages get the Signal timestamp of `now`, as on Signal."""

    now: datetime | None = None

    async def send_group_message(self, group_id: str, text: str) -> int:
        if self.now is not None:
            self._next_timestamp = max(self._next_timestamp, ms(self.now))
        return await super().send_group_message(group_id, text)


class World:
    """ODIN with one store and one client: ticks of the engine and events from the chat."""

    def __init__(self, store: Store, config: Config = CONFIG) -> None:
        self.store = store
        self.config = config
        self.client = Client(number=BOT)
        self.failures: list[SendFailure] = []

    def tick(self, now: datetime) -> None:
        self.client.now = now
        self.failures = []
        asyncio.run(reconcile(self.config, self.store, self.client, ACCOUNT, now, self.failures))

    def run(self, start: datetime, end: datetime) -> list[SendFailure]:
        """Tick every 15 minutes from `start` until before `end`; returns every failed send."""
        failures = []
        now = start
        while now < end:
            self.tick(now)
            failures += self.failures
            now += timedelta(minutes=15)
        return failures

    def chat(self, now: datetime, *events: GroupMessage | ReactionEvent) -> list[str]:
        """Deliver `events` at `now`; returns the replies sent to the flat group."""
        self.client.now = now
        before = len(self.client.sent)
        for event in events:
            self.client.inject(event)
        self.client.close()
        clock = FixedClock(now)
        asyncio.run(consume_events(self.client, self.store, self.config, ACCOUNT, clock))
        return [sent.text for sent in self.client.sent[before:]]

    def say(self, text: str, now: datetime) -> list[str]:
        return self.chat(now, message(text, now))

    def react(
        self,
        now: datetime,
        week: date = WEEK,
        kind: MessageKind = MessageKind.HIATUS_REQUEST,
        *,
        reactor: str = BEN,
        remove: bool = False,
    ) -> None:
        tracked = self.store.tracked_message(week, kind)
        assert tracked is not None, f"{kind} not tracked"
        event = ReactionEvent(
            emoji="👍",
            reactor=reactor,
            target_author=tracked.author,
            target_timestamp=tracked.timestamp,
            group_id=tracked.group_id,
            is_remove=remove,
            timestamp=ms(now),
        )
        self.chat(now, event)

    def hiatus(self, now: datetime, week: date = WEEK) -> None:
        """/hiatus at `now`, confirmed a minute later."""
        self.say("/hiatus", now)
        self.react(now + timedelta(minutes=1), week)

    def dinner_texts(self) -> list[str]:
        return [sent.text for sent in self.client.sent if sent.group_id == DINNER]

    def flat_texts(self) -> list[str]:
        """The weekly cycle's messages to the flat group (first lines), without command replies."""
        texts = [sent.text.split("\n")[0] for sent in self.client.sent if sent.group_id == FLAT]
        return [text for text in texts if text.startswith(("ASK", "NUDGE", "TALLY"))]

    def outcomes(self, week: date = WEEK) -> dict[Action, Outcome]:
        found = {action: self.store.action_outcome(week, action) for action in Action}
        return {action: outcome for action, outcome in found.items() if outcome is not None}


def message(text: str, now: datetime) -> GroupMessage:
    return GroupMessage(
        sender=ANNA, sender_name="Anna", text=text, group_id=FLAT, timestamp=ms(now)
    )


def run_command(store: Store, text: str, now: datetime, config: Config = CONFIG) -> list[str]:
    ctx = CommandContext(
        base=config, config=config, store=store, now=now, sender=ANNA, sender_name="Anna"
    )
    return handle(text, ctx)


ALL_SKIPPED = {
    Action.FLAT_ASK: Outcome.SKIPPED,
    Action.NUDGE: Outcome.SKIPPED,
    Action.CANCELLATION: Outcome.SKIPPED,
    Action.TALLY: Outcome.SKIPPED,
}


@pytest.fixture
def world(store: Store) -> World:
    return World(store)


# --- /hiatus: the command -----------------------------------------------------------------------


def test_hiatus_asks_for_confirmation_and_shows_the_notice(store: Store) -> None:
    [reply] = run_command(store, "/hiatus", local(5, 10))
    assert isinstance(reply, TrackedReply)
    assert (reply.week, reply.kind) == (WEEK, MessageKind.HIATUS_REQUEST)
    assert reply == (
        "Odin in Pause schicken? Dann reagiert mit 👍 auf diese Nachricht. Bis jemand /resume "
        "schreibt, frage ich die WG nicht mehr und schicke der Essensgruppe nichts – außer "
        "einmal, was unten steht.\n"
        "Ohne 👍 passiert nichts; die Anfrage verfällt, wenn das Essen beginnt (So 11.10. 18:00)."
        f"\n\nDas geht an die Essensgruppe:\n\n{NOTICE}"
    )
    # Who asked is stored; nothing has taken effect.
    request = store.hiatus_request(WEEK)
    assert request is not None
    assert (request.requested_by, request.started_at) == ("Anna", None)
    assert store.active_hiatus() is None


def test_hiatus_after_the_flat_ask_says_it_cancels_the_week_first(store: Store) -> None:
    store.record_action(WEEK, Action.FLAT_ASK, local(6, 18))
    [reply] = run_command(store, "/hiatus", local(7, 10))
    lines = reply.split("\n")
    assert lines[1] == (
        "Die Frage zum Essen am Sonntag, 11.10. ist schon raus – das sage ich vorher ab, genau "
        "wie mit /cancel."
    )
    assert reply.endswith(f"Das geht an die Essensgruppe:\n\n{CANCELLATION}\n\n{NOTICE}")


def test_hiatus_without_its_template_shows_the_cancellation_once(store: Store) -> None:
    store.record_action(WEEK, Action.FLAT_ASK, local(6, 18))
    [reply] = run_command(store, "/hiatus", local(7, 10), NO_HIATUS_TEXT)
    assert hiatus_command.NO_TEXT in reply.split("\n")
    assert reply.endswith(f"Das geht an die Essensgruppe:\n\n{CANCELLATION}")
    assert reply.count("ABGESAGT") == 1


def test_hiatus_without_its_template_after_a_cancellation_posts_nothing(store: Store) -> None:
    store.record_action(WEEK, Action.FLAT_ASK, local(6, 18))
    store.record_action(WEEK, Action.CANCELLATION, local(7, 18))
    [reply] = run_command(store, "/hiatus", local(8, 10), NO_HIATUS_TEXT)
    assert reply.endswith(
        "Die Essensgruppe hat die Absage für das Essen am Sonntag, 11.10. schon; mehr schicke ich "
        "ihr nicht."
    )
    assert "ABGESAGT" not in reply


def test_hiatus_takes_no_arguments(store: Store) -> None:
    assert run_command(store, "/hiatus now", local(5, 10)) == [hiatus_command.USAGE]
    assert run_command(store, "/resume now", local(5, 10)) == [hiatus_command.RESUME_USAGE]


def test_hiatus_and_resume_are_listed_in_help(store: Store) -> None:
    [reply] = run_command(store, "/help", local(5, 10))
    assert "/hiatus – Schickt Odin in Pause" in reply
    assert "/resume – Beendet die Pause" in reply


# --- /hiatus before the week's flat ask ---------------------------------------------------------


def test_hiatus_before_the_flat_ask_sends_nothing_for_weeks(world: World) -> None:
    world.hiatus(local(5, 10))
    failures = world.run(local(5, 10, 15), local(1, 19, month=11))
    # Only the notice, once; no flat ask, nudge, decision or tally for three weeks.
    assert world.dinner_texts() == [NOTICE]
    assert world.flat_texts() == []
    assert failures == []
    for week in (WEEK, NEXT, AFTER):
        assert world.outcomes(week) == ALL_SKIPPED
        assert untracked_warnings(world.store, week) == []
    hiatus = world.store.active_hiatus()
    assert hiatus is not None
    assert (hiatus.from_day, hiatus.notice) == (WEEK, Outcome.SENT)
    # The weeks of the hiatus are finished: nothing is left for the catch-up.
    assert world.store.unfinished_weeks_before(date(2026, 11, 1)) == []


def test_the_notice_goes_out_on_the_next_tick(world: World) -> None:
    world.hiatus(local(5, 10))
    world.tick(local(5, 10, 2))
    assert world.dinner_texts() == [NOTICE]
    # The request is gone: a late reaction on it changes nothing.
    assert world.store.tracked_message(WEEK, MessageKind.HIATUS_REQUEST) is None
    world.tick(local(5, 10, 3))
    assert world.dinner_texts() == [NOTICE]


def test_an_unconfirmed_hiatus_does_nothing_and_lapses(world: World) -> None:
    world.say("/hiatus", local(5, 10))
    world.run(local(5, 10), local(11, 19))
    assert world.store.active_hiatus() is None
    assert world.flat_texts() == ["ASK 👍 bis 18:00", "NUDGE 18:00"]
    assert world.dinner_texts() == [CANCELLATION]
    # Too late now: the request belonged to the week whose dinner has started.
    world.react(local(11, 19))
    world.tick(local(11, 19, 1))
    assert world.store.active_hiatus() is None


def test_a_withdrawn_confirmation_does_nothing(world: World) -> None:
    world.say("/hiatus", local(5, 10))
    world.react(local(5, 10, 1))
    world.react(local(5, 10, 2), remove=True)
    world.tick(local(5, 10, 3))
    assert world.store.active_hiatus() is None
    assert world.dinner_texts() == []


# --- /hiatus after the flat ask or the announcement --------------------------------------------


def test_hiatus_after_the_flat_ask_cancels_the_week_once(world: World) -> None:
    world.run(local(6, 17), local(7, 10))
    assert world.flat_texts() == ["ASK 👍 bis 18:00"]
    world.hiatus(local(7, 10))
    failures = world.run(local(7, 10, 2), local(25, 19))
    assert world.dinner_texts() == [CANCELLATION, NOTICE]
    assert world.flat_texts() == ["ASK 👍 bis 18:00"]
    assert failures == []
    assert world.outcomes() == {
        Action.FLAT_ASK: Outcome.SENT,
        Action.NUDGE: Outcome.SKIPPED,
        Action.CANCELLATION: Outcome.SENT,
        Action.TALLY: Outcome.SKIPPED,
    }
    for week in (NEXT, AFTER):
        assert world.outcomes(week) == ALL_SKIPPED
    hiatus = world.store.active_hiatus()
    assert hiatus is not None
    assert hiatus.from_day is not None
    assert hiatus.from_day > WEEK


def test_hiatus_after_the_announcement_cancels_the_week_once(world: World) -> None:
    world.run(local(6, 17), local(6, 18, 15))
    world.react(local(6, 19), kind=MessageKind.FLAT_POLL)
    world.run(local(6, 19, 15), local(8, 10))
    assert world.dinner_texts() == [ANNOUNCEMENT]
    world.hiatus(local(8, 10))
    world.run(local(8, 10, 2), local(18, 19))
    assert world.dinner_texts() == [ANNOUNCEMENT, CANCELLATION, NOTICE]
    assert world.flat_texts() == ["ASK 👍 bis 18:00"]  # no tally
    assert world.outcomes()[Action.TALLY] is Outcome.SKIPPED
    lines = status(CONFIG, world.store, local(9, 10)).split("\n")
    assert lines[4] == "❌ Absage gesendet (Do 10:02) – per /hiatus"


def test_hiatus_in_a_cancelled_week_only_posts_the_notice(world: World) -> None:
    world.run(local(6, 17), local(8, 10))
    assert world.dinner_texts() == [CANCELLATION]
    world.hiatus(local(8, 10))
    world.run(local(8, 10, 2), local(18, 19))
    assert world.dinner_texts() == [CANCELLATION, NOTICE]


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (local(5, 10), [CANCELLATION]),  # before the flat ask: the cancellation is the notice
        (local(7, 10), [CANCELLATION]),  # after it: the week's cancellation, not a second one
    ],
)
def test_without_its_template_the_dinner_group_gets_one_cancellation(
    store: Store, start: datetime, expected: list[str]
) -> None:
    world = World(store, NO_HIATUS_TEXT)
    world.run(local(6, 17), start)
    world.hiatus(start)
    world.run(start + timedelta(minutes=2), local(25, 19))
    assert world.dinner_texts() == expected
    hiatus = store.active_hiatus()
    assert hiatus is not None
    assert hiatus.notice is (Outcome.SENT if start < local(6, 18) else Outcome.SKIPPED)


def test_a_failed_notice_is_retried_and_reported(world: World) -> None:
    world.hiatus(local(5, 10))
    world.client.fail_sends(SignalApiError(500, "down"))
    world.tick(local(5, 10, 2))
    assert world.dinner_texts() == []
    assert world.failures == [SendFailure(WEEK, Action.HIATUS_NOTICE, "SignalApiError")]
    world.tick(local(5, 10, 3))
    assert world.failures == []
    assert world.dinner_texts() == [NOTICE]


def test_the_notice_follows_a_cancellation_that_failed(world: World) -> None:
    world.run(local(6, 17), local(7, 10))
    world.hiatus(local(7, 10))
    world.client.fail_sends(SignalApiError(500, "down"))
    world.tick(local(7, 10, 2))
    assert world.dinner_texts() == []
    assert [f.action for f in world.failures] == [Action.CANCELLATION]
    world.tick(local(7, 10, 3))
    assert world.dinner_texts() == [CANCELLATION, NOTICE]


# --- /resume ------------------------------------------------------------------------------------


def test_resume_between_weeks_runs_the_next_week_normally(world: World) -> None:
    world.hiatus(local(5, 10))
    world.run(local(5, 10, 2), local(12, 10))
    [reply] = world.say("/resume", local(12, 10))
    assert reply == (
        "Pause beendet ✅ Ab jetzt läuft alles wieder wie gewohnt.\n"
        "/status zeigt, was als Nächstes kommt."
    )
    world.run(local(12, 10, 1), local(18, 19))
    # Week 11.10. stays quiet; week 18.10. runs as usual, nothing caught up.
    assert world.flat_texts() == ["ASK 👍 bis 18:00", "NUDGE 18:00"]
    assert world.dinner_texts() == [NOTICE, CANCELLATION]
    assert world.outcomes(WEEK) == ALL_SKIPPED
    assert world.outcomes(NEXT)[Action.FLAT_ASK] is Outcome.SENT
    assert world.store.active_hiatus() is None


def test_resume_before_the_flat_ask_of_the_first_hiatus_week_runs_it(world: World) -> None:
    world.hiatus(local(5, 10))
    world.tick(local(5, 10, 2))
    world.say("/resume", local(6, 10))
    world.run(local(6, 10), local(7, 19))
    assert world.flat_texts() == ["ASK 👍 bis 18:00", "NUDGE 18:00"]
    assert world.dinner_texts() == [NOTICE, CANCELLATION]


def test_resume_mid_week_leaves_that_week_off(world: World) -> None:
    world.hiatus(local(5, 10))
    world.run(local(5, 10, 2), local(14, 10))
    [reply] = world.say("/resume", local(14, 10))
    assert reply.split("\n")[1] == (
        "Für das Essen am Sonntag, 18.10. war die Frage an die WG schon fällig – das fällt noch "
        "aus, ohne Nachricht an die Essensgruppe."
    )
    world.run(local(14, 10), local(25, 19))
    # Week 18.10. sends nothing (its flat ask was due in the hiatus); 25.10. runs normally.
    assert world.outcomes(NEXT) == ALL_SKIPPED
    assert world.flat_texts() == ["ASK 👍 bis 18:00", "NUDGE 18:00"]
    assert world.dinner_texts() == [NOTICE, CANCELLATION]
    assert world.outcomes(AFTER)[Action.FLAT_ASK] is Outcome.SENT


def test_resume_after_downtime_posts_no_late_flat_ask(world: World) -> None:
    world.hiatus(local(5, 10))
    world.run(local(5, 10, 2), local(13, 10))
    # ODIN is down over Tuesday's flat ask; the flat resumes on Wednesday morning, before the
    # deadline, while the flat ask would still be in its catch-up window.
    run_command(world.store, "/resume", local(14, 10))
    world.run(local(14, 10), local(18, 19))
    assert world.flat_texts() == []
    assert world.dinner_texts() == [NOTICE]
    assert world.outcomes(NEXT) == ALL_SKIPPED


def test_resume_after_a_long_downtime_backfills_nothing(world: World) -> None:
    world.hiatus(local(5, 10))
    world.tick(local(5, 10, 2))
    # Down for weeks; resumed while still down, back up the week after.
    run_command(world.store, "/resume", local(19, 10))
    world.run(local(26, 10), local(1, 19, month=11))
    assert world.dinner_texts() == [NOTICE, CANCELLATION]
    assert world.flat_texts() == ["ASK 👍 bis 18:00", "NUDGE 18:00"]


def test_nothing_is_sent_twice_across_a_restart(store: Store) -> None:
    first = World(store)
    first.run(local(6, 17), local(7, 10))
    first.hiatus(local(7, 10))
    first.run(local(7, 10, 2), local(7, 11))
    assert first.dinner_texts() == [CANCELLATION, NOTICE]
    # A restart: a new client, the same database.
    second = World(store)
    second.run(local(7, 11), local(13, 10))
    assert second.client.sent == []
    second.say("/resume", local(13, 10))
    restarted = World(store)
    restarted.run(local(13, 10), local(18, 19))
    assert restarted.flat_texts() == ["ASK 👍 bis 18:00", "NUDGE 18:00"]
    assert restarted.dinner_texts() == [CANCELLATION]


def test_resume_before_the_notice_went_out_skips_it(world: World) -> None:
    world.hiatus(local(5, 10))
    world.client.fail_sends(SignalApiError(500, "down"))
    world.tick(local(5, 10, 2))
    run_command(world.store, "/resume", local(5, 10, 3))
    world.run(local(5, 10, 4), local(11, 19))
    assert world.dinner_texts() == [CANCELLATION]
    [hiatus] = world.store.hiatuses()
    assert hiatus.notice is Outcome.SKIPPED


def test_a_second_hiatus_in_the_same_week(world: World) -> None:
    world.hiatus(local(5, 10))
    world.tick(local(5, 10, 2))
    world.say("/resume", local(5, 11))
    world.hiatus(local(5, 12))
    world.tick(local(5, 12, 2))
    assert world.dinner_texts() == [NOTICE, NOTICE]
    assert len(world.store.hiatuses()) == 2
    world.run(local(5, 12, 3), local(11, 19))
    assert world.flat_texts() == []


# --- Hints for a double /hiatus or /resume ------------------------------------------------------


def test_hiatus_during_a_hiatus_gives_a_hint(world: World) -> None:
    world.hiatus(local(5, 10))
    world.tick(local(5, 10, 2))
    assert world.say("/hiatus", local(14, 9)) == [
        "Ich mache schon Pause, seit Mo 05.10. 10:02 (von Anna). /resume beendet die Pause."
    ]


def test_hiatus_while_requested_gives_a_hint(world: World) -> None:
    world.say("/hiatus", local(5, 10))
    assert world.say("/hiatus", local(5, 11)) == [
        "Die Pause ist schon angefragt (Mo 05.10. 10:00) – reagiert mit 👍 auf meine Nachricht "
        "von da."
    ]


def test_resume_while_awake_gives_a_hint(world: World) -> None:
    assert world.say("/resume", local(5, 10)) == [hiatus_command.NOT_ON_HIATUS]
    world.say("/hiatus", local(5, 10))
    assert world.say("/resume", local(5, 11)) == [
        f"{hiatus_command.NOT_ON_HIATUS}\n"
        "Die angefragte Pause beginnt erst, wenn jemand mit 👍 auf meine Nachricht dazu "
        "reagiert; ohne 👍 verfällt sie, wenn das Essen beginnt (So 11.10. 18:00)."
    ]


# --- Other commands during a hiatus -------------------------------------------------------------


def test_cancel_is_refused_during_a_hiatus(world: World) -> None:
    world.hiatus(local(5, 10))
    world.run(local(5, 10, 2), local(7, 10))
    assert world.say("/cancel", local(7, 10)) == [cancel_command.HIATUS]
    # /skip with this week's date is /cancel once the week has started.
    assert world.say("/skip 2026-10-11", local(7, 10)) == [cancel_command.HIATUS]


def test_cancel_is_refused_for_a_week_left_off_by_a_resume(world: World) -> None:
    world.hiatus(local(5, 10))
    world.run(local(5, 10, 2), local(14, 10))
    world.say("/resume", local(14, 10))
    assert world.say("/cancel", local(14, 11)) == [
        cancel_command.HIATUS_WEEK.format(day="Sonntag, 18.10.")
    ]


def test_a_cancel_request_confirmed_in_a_hiatus_week_sends_nothing(world: World) -> None:
    world.say("/cancel", local(5, 9))
    world.hiatus(local(5, 10))
    world.react(local(5, 11), kind=MessageKind.CANCEL_REQUEST)
    world.run(local(5, 11), local(11, 19))
    assert world.dinner_texts() == [NOTICE]


def test_skip_is_accepted_during_a_hiatus(world: World) -> None:
    world.hiatus(local(5, 10))
    world.tick(local(5, 10, 2))
    [inside] = world.say("/skip 2026-10-18", local(6, 10))
    assert inside.startswith("Eingetragen: Am Sonntag, 18.10.2026 gibt es kein Essen.")
    assert inside.endswith(
        "Ich mache gerade Pause: Fällt der Tag noch in die Pause, schicke ich auch diese Absage "
        "nicht.\n/unskip 2026-10-18 nimmt das zurück."
    )
    world.say("/skip 2026-10-25", local(6, 10))
    world.run(local(6, 10), local(19, 10))
    world.say("/resume", local(19, 10))
    world.run(local(19, 10), local(25, 19))
    # The skip date inside the hiatus sends nothing; the one after /resume its cancellation.
    assert world.dinner_texts() == [NOTICE, CANCELLATION]
    assert world.store.action_time(AFTER, Action.CANCELLATION) == local(21, 18)
    assert world.flat_texts() == []


def test_a_week_dropped_in_a_hiatus_gets_no_cancellation(world: World) -> None:
    world.hiatus(local(5, 10))
    world.tick(local(5, 10, 2))
    world.store.record_dropped_week(NEXT, local(11, 18))
    world.run(local(11, 18), local(18, 19))
    assert world.dinner_texts() == [NOTICE]


# --- /status ------------------------------------------------------------------------------------


def test_status_shows_a_requested_hiatus(world: World) -> None:
    world.say("/hiatus", local(5, 10))
    lines = status(CONFIG, world.store, local(5, 10, 30)).split("\n")
    assert "😴 Pause per /hiatus angefragt (Mo 05.10. 10:00) – wartet auf 👍" in lines
    world.react(local(5, 10, 31))
    lines = status(CONFIG, world.store, local(5, 10, 32)).split("\n")
    assert "😴 Pause per /hiatus angefragt (Mo 05.10. 10:00) – bestätigt, beginnt gleich" in lines


def test_status_shows_the_hiatus_instead_of_the_week(world: World) -> None:
    world.hiatus(local(5, 10))
    world.run(local(5, 10, 2), local(14, 10))
    [reply] = world.say("/status", local(14, 10))
    assert reply == (
        "Sonntag, 18.10.\n"
        "😴 Kein Essen – Pause per /hiatus\n"
        "😴 Pause seit Mo 05.10. 10:02 (von Anna): keine Frage an die WG, nichts an die "
        "Essensgruppe.\n"
        "✅ Hinweis an die Essensgruppe gesendet (Mo 05.10. 10:02)\n"
        "/resume beendet die Pause."
    )


def test_status_shows_the_week_cancelled_by_the_hiatus(world: World) -> None:
    world.run(local(6, 17), local(7, 10))
    world.hiatus(local(7, 10))
    world.tick(local(7, 10, 2))
    lines = status(CONFIG, world.store, local(7, 11)).split("\n")
    assert lines[0] == "Sonntag, 11.10."
    assert "❌ Absage gesendet (Mi 10:02) – per /hiatus" in lines
    assert lines[-3:] == [
        "😴 Pause seit Mi 07.10. 10:02 (von Anna): keine Frage an die WG, nichts an die "
        "Essensgruppe.",
        "✅ Hinweis an die Essensgruppe gesendet (Mi 07.10. 10:02)",
        "/resume beendet die Pause.",
    ]


def test_status_after_resume_skips_the_week_left_off(world: World) -> None:
    world.hiatus(local(5, 10))
    world.run(local(5, 10, 2), local(14, 10))
    world.say("/resume", local(14, 10))
    assert status(CONFIG, world.store, local(14, 11)) == (
        "Sonntag, 18.10.\n"
        "😴 Kein Essen – Pause per /hiatus\n"
        "Nächste Aktion: Frage an die WG, Di 18:00"
    )
