"""/cancel end to end: the command, its tracked reply, the confirming reaction and the engine."""

import asyncio
from datetime import date, datetime, timedelta

import pytest
from helpers import local, ms

from odin.clock import FixedClock
from odin.commands import CommandContext, TrackedReply, handle
from odin.commands.cancel import (
    ALREADY_CANCELLED,
    CANCELLATION_SKIPPED,
    DROPPED_WEEK,
    USAGE,
)
from odin.config import parse_config
from odin.engine import Account, reconcile
from odin.events import consume_events
from odin.signal import FakeSignalClient, GroupMessage, ReactionEvent, SendResponseUnreadable
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
# Default schedule: ask Tue 18:00, nudge Wed 12:00, decision Wed 18:00, tally Fri 14:00,
# dinner Sun 18:00.
CONFIG = parse_config({"templates": TEMPLATES})

BOT = "+490000000000"
FLAT, DINNER = "group.flat=", "group.dinner="
ACCOUNT = Account(number=BOT, flat_group_id=FLAT, dinner_group_id=DINNER)
ANNA, BEN = "+4915100000001", "+4915100000002"

WEEK = date(2026, 10, 11)
CANCELLATION = "ABGESAGT Sonntag\n\nCANCELLED Sunday"


class Client(FakeSignalClient):
    """Sent messages get the Signal timestamp of `now`, as on Signal."""

    now: datetime | None = None

    async def send_group_message(self, group_id: str, text: str) -> int:
        if self.now is not None:
            self._next_timestamp = max(self._next_timestamp, ms(self.now))
        return await super().send_group_message(group_id, text)


class World:
    """ODIN with one store and one client: ticks of the engine and events from the chat."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.client = Client(number=BOT)

    def tick(self, now: datetime) -> None:
        self.client.now = now
        asyncio.run(reconcile(CONFIG, self.store, self.client, ACCOUNT, now))

    def run(self, start: datetime, end: datetime) -> None:
        now = start
        while now < end:
            self.tick(now)
            now += timedelta(minutes=15)

    def chat(self, now: datetime, *events: GroupMessage | ReactionEvent) -> list[str]:
        """Deliver `events` at `now`; returns the replies sent to the flat group."""
        self.client.now = now
        before = len(self.client.sent)
        for event in events:
            self.client.inject(event)
        self.client.close()
        clock = FixedClock(now)
        asyncio.run(consume_events(self.client, self.store, CONFIG, ACCOUNT, clock))
        return [sent.text for sent in self.client.sent[before:]]

    def cancel(self, now: datetime) -> list[str]:
        return self.chat(now, message("/cancel", now))

    def react(
        self,
        now: datetime,
        kind: MessageKind = MessageKind.CANCEL_REQUEST,
        *,
        reactor: str = BEN,
        emoji: str = "👍",
        remove: bool = False,
    ) -> None:
        tracked = self.store.tracked_message(WEEK, kind)
        assert tracked is not None, f"{kind} not tracked"
        event = ReactionEvent(
            emoji=emoji,
            reactor=reactor,
            target_author=tracked.author,
            target_timestamp=tracked.timestamp,
            group_id=tracked.group_id,
            is_remove=remove,
            timestamp=ms(now),
        )
        self.chat(now, event)

    def dinner_texts(self) -> list[str]:
        return [sent.text for sent in self.client.sent if sent.group_id == DINNER]

    def flat_texts(self) -> list[str]:
        """The weekly cycle's messages to the flat group (first lines), without command replies."""
        texts = [sent.text.split("\n")[0] for sent in self.client.sent if sent.group_id == FLAT]
        return [text for text in texts if text.startswith(("ASK", "NUDGE", "TALLY"))]

    def outcomes(self) -> dict[Action, Outcome]:
        found = {action: self.store.action_outcome(WEEK, action) for action in Action}
        return {action: outcome for action, outcome in found.items() if outcome is not None}


def message(text: str, now: datetime) -> GroupMessage:
    return GroupMessage(
        sender=ANNA, sender_name="Anna", text=text, group_id=FLAT, timestamp=ms(now)
    )


@pytest.fixture
def world(store: Store) -> World:
    return World(store)


def run_command(store: Store, text: str, now: datetime) -> list[str]:
    ctx = CommandContext(
        base=CONFIG, config=CONFIG, store=store, now=now, sender=ANNA, sender_name="Anna"
    )
    return handle(text, ctx)


# --- The command --------------------------------------------------------------------------------


def test_cancel_asks_for_confirmation_and_shows_the_cancellation(store: Store) -> None:
    [reply] = run_command(store, "/cancel", local(5, 10))
    assert isinstance(reply, TrackedReply)
    assert (reply.week, reply.kind) == (WEEK, MessageKind.CANCEL_REQUEST)
    assert reply == (
        "Das Essen am Sonntag, 11.10. absagen? Dann reagiert mit 👍 auf diese Nachricht – "
        "ich schicke der Essensgruppe dann diese Absage:\n"
        "Ohne 👍 passiert nichts; die Anfrage verfällt, wenn das Essen beginnt (So 11.10. 18:00)."
        f"\n\n{CANCELLATION}"
    )
    # The command itself writes nothing.
    assert store.tracked_message(WEEK, MessageKind.CANCEL_REQUEST) is None
    assert not store.has_any_action(WEEK)


def test_cancel_takes_no_arguments(store: Store) -> None:
    assert run_command(store, "/cancel now", local(5, 10)) == [USAGE]


def test_after_dinner_start_it_is_about_next_week(store: Store) -> None:
    [reply] = run_command(store, "!CANCEL", local(11, 18))
    assert isinstance(reply, TrackedReply)
    assert reply.week == WEEK + timedelta(weeks=1)
    assert reply.startswith("Das Essen am Sonntag, 18.10. absagen?")


def test_after_the_announcement_it_says_so(store: Store) -> None:
    store.record_action(WEEK, Action.ANNOUNCEMENT, local(7, 18))
    announcement = store.track_message(WEEK, MessageKind.DINNER_ANNOUNCEMENT, DINNER, BOT, 5)
    store.set_reaction(announcement, BEN, "👍", local(8, 9))
    [reply] = run_command(store, "/cancel", local(8, 10))
    assert reply.splitlines()[1] == (
        "Die Einladung ist schon raus (1× 👍); die Absage kommt dann hinterher."
    )


def test_an_already_cancelled_week_is_refused(store: Store) -> None:
    store.record_action(WEEK, Action.CANCELLATION, local(7, 18))
    assert run_command(store, "/cancel", local(8, 10)) == [
        ALREADY_CANCELLED.format(day="Sonntag, 11.10.", at="Mi 07.10. 18:00")
    ]


def test_a_skipped_cancellation_is_refused(store: Store) -> None:
    store.record_action(WEEK, Action.CANCELLATION, local(11, 19), Outcome.SKIPPED)
    assert run_command(store, "/cancel", local(8, 10)) == [
        CANCELLATION_SKIPPED.format(day="Sonntag, 11.10.")
    ]


def test_a_dropped_week_is_refused(store: Store) -> None:
    store.record_dropped_week(WEEK, local(4, 18))
    assert run_command(store, "/cancel", local(5, 10)) == [
        DROPPED_WEEK.format(day="Sonntag, 11.10.")
    ]


def test_listed_in_help(store: Store) -> None:
    [reply] = run_command(store, "/help", local(5, 10))
    assert "/cancel – Sagt das Essen dieser Woche ab – nach Bestätigung per Reaktion." in (
        reply.splitlines()
    )


# --- Tracking the request -----------------------------------------------------------------------


def test_the_reply_is_tracked_as_the_cancel_request(world: World) -> None:
    [reply] = world.cancel(local(5, 10))
    request = world.store.tracked_message(WEEK, MessageKind.CANCEL_REQUEST)
    assert request is not None
    assert (request.group_id, request.author) == (FLAT, BOT)
    [sent] = world.client.sent
    assert (sent.text, sent.timestamp) == (reply, request.timestamp)


def test_a_second_cancel_points_to_the_first_request(world: World) -> None:
    world.cancel(local(5, 10))
    first = world.store.tracked_message(WEEK, MessageKind.CANCEL_REQUEST)
    assert world.cancel(local(5, 11)) == [
        "Die Absage für das Essen am Sonntag, 11.10. ist schon angefragt (Mo 05.10. 10:00) – "
        "reagiert mit 👍 auf meine Nachricht von da."
    ]
    assert world.store.tracked_message(WEEK, MessageKind.CANCEL_REQUEST) == first


def test_two_requests_at_once_track_only_the_first(world: World) -> None:
    now = local(5, 10)
    replies = world.chat(now, message("/cancel", now), message("/cancel", now))
    # Both commands ran before either reply was sent, so both asked for a confirmation.
    assert len(replies) == 2
    request = world.store.tracked_message(WEEK, MessageKind.CANCEL_REQUEST)
    assert request is not None and request.timestamp == world.client.sent[0].timestamp


def test_an_unreadable_send_leaves_the_request_untracked(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    world.client.fail_sends(SendResponseUnreadable("{}"), delivered=True)
    world.cancel(local(5, 10))
    assert world.store.tracked_message(WEEK, MessageKind.CANCEL_REQUEST) is None
    assert "sent a command reply, but" in caplog.text
    # So it can be asked again.
    world.cancel(local(5, 11))
    assert world.store.tracked_message(WEEK, MessageKind.CANCEL_REQUEST) is not None


# --- The engine ---------------------------------------------------------------------------------


def test_confirmed_before_the_flat_ask_cancels_the_whole_week(world: World) -> None:
    world.run(local(5, 0), local(5, 10))
    world.cancel(local(5, 10))
    world.react(local(5, 10, 5))
    world.run(local(5, 10, 15), local(12, 0))

    assert world.dinner_texts() == [CANCELLATION]
    assert world.flat_texts() == []
    assert world.outcomes() == {
        Action.FLAT_ASK: Outcome.SKIPPED,
        Action.NUDGE: Outcome.SKIPPED,
        Action.CANCELLATION: Outcome.SENT,
        Action.TALLY: Outcome.SKIPPED,
    }
    assert world.store.action_time(WEEK, Action.CANCELLATION) == local(5, 10, 15)


def test_confirmed_during_the_poll_is_the_decision(world: World) -> None:
    world.run(local(5, 0), local(6, 19))
    world.react(local(6, 19), MessageKind.FLAT_POLL, reactor=ANNA)  # dinner was going to be on
    world.cancel(local(6, 20))
    world.react(local(6, 20, 5))
    world.run(local(6, 20, 15), local(12, 0))

    assert world.dinner_texts() == [CANCELLATION]
    assert world.outcomes() == {
        Action.FLAT_ASK: Outcome.SENT,
        Action.NUDGE: Outcome.SKIPPED,
        Action.CANCELLATION: Outcome.SENT,
        Action.TALLY: Outcome.SKIPPED,
    }


def test_confirmed_after_the_announcement_follows_it_and_drops_the_tally(world: World) -> None:
    world.run(local(5, 0), local(6, 19))
    world.react(local(6, 19), MessageKind.FLAT_POLL, reactor=ANNA)
    world.run(local(6, 19), local(8, 9))
    world.cancel(local(8, 9))
    world.react(local(8, 9, 5))
    world.run(local(8, 9, 15), local(12, 0))

    assert world.dinner_texts() == ["ESSEN 18:00\n\nDINNER 18:00", CANCELLATION]
    assert world.outcomes() == {
        Action.FLAT_ASK: Outcome.SENT,
        Action.NUDGE: Outcome.SKIPPED,
        Action.ANNOUNCEMENT: Outcome.SENT,
        Action.CANCELLATION: Outcome.SENT,
        Action.TALLY: Outcome.SKIPPED,
    }
    assert world.flat_texts() == ["ASK 👍 bis 18:00"]


def test_confirmed_after_the_tally_is_still_sent(world: World) -> None:
    world.run(local(5, 0), local(6, 19))
    world.react(local(6, 19), MessageKind.FLAT_POLL, reactor=ANNA)
    world.run(local(6, 19), local(10, 12))
    world.cancel(local(10, 12))
    world.react(local(10, 12, 5))
    world.run(local(10, 12, 15), local(12, 0))

    assert world.dinner_texts() == ["ESSEN 18:00\n\nDINNER 18:00", CANCELLATION]
    assert world.outcomes()[Action.TALLY] is Outcome.SENT


def test_without_confirmation_nothing_happens(world: World) -> None:
    world.run(local(5, 0), local(6, 19))
    world.react(local(6, 19), MessageKind.FLAT_POLL, reactor=ANNA)
    world.cancel(local(6, 20))
    world.react(local(6, 20, 5), emoji="❤️")  # another emoji does not confirm
    world.react(local(6, 20, 6), reactor=ANNA)
    world.react(local(6, 20, 7), reactor=ANNA, remove=True)  # withdrawn before the tick
    world.run(local(6, 20, 15), local(12, 0))

    assert world.dinner_texts() == ["ESSEN 18:00\n\nDINNER 18:00"]
    assert world.outcomes()[Action.TALLY] is Outcome.SENT


def test_the_automatic_cancellation_is_never_followed_by_a_second_one(world: World) -> None:
    world.run(local(5, 0), local(6, 20))
    world.cancel(local(6, 20))
    world.run(local(6, 20), local(7, 19))  # nobody confirmed the poll: cancelled at 18:00
    world.react(local(7, 19))
    world.run(local(7, 19), local(12, 0))

    assert world.dinner_texts() == [CANCELLATION]


def test_a_confirmation_after_dinner_start_does_nothing(world: World) -> None:
    world.run(local(5, 0), local(6, 19))
    world.react(local(6, 19), MessageKind.FLAT_POLL, reactor=ANNA)
    world.cancel(local(9, 12))
    world.run(local(6, 19), local(11, 18, 15))
    world.react(local(11, 18, 30))
    world.run(local(11, 18, 30), local(13, 0))

    assert world.dinner_texts() == ["ESSEN 18:00\n\nDINNER 18:00"]


def test_a_failed_cancellation_is_retried_and_sent_once(world: World) -> None:
    world.cancel(local(5, 10))
    world.react(local(5, 10, 5))
    world.client.fail_sends(ConnectionError("unreachable"))
    world.tick(local(5, 10, 15))
    assert world.dinner_texts() == []
    assert not world.store.has_any_action(WEEK)
    world.run(local(5, 10, 30), local(6, 0))
    assert world.dinner_texts() == [CANCELLATION]


def test_a_cancelled_week_does_not_ask_an_untracked_flat_poll_again(world: World) -> None:
    world.run(local(5, 0), local(6, 18))
    # The flat ask is posted untracked, and the retry of it fails once.
    world.client.fail_sends(SendResponseUnreadable("{}"), delivered=True)
    world.client.fail_sends(ConnectionError("unreachable"))
    world.tick(local(6, 18))
    assert world.store.tracked_message(WEEK, MessageKind.FLAT_POLL) is None
    world.cancel(local(6, 18, 5))
    world.react(local(6, 18, 10))
    world.run(local(6, 18, 15), local(12, 0))

    assert world.dinner_texts() == [CANCELLATION]
    assert world.flat_texts() == ["ASK 👍 bis 18:00"]
    assert Action.FLAT_ASK_RETRY not in world.outcomes()


def test_a_cancelled_week_gets_no_untracked_announcement_notice(world: World) -> None:
    world.run(local(5, 0), local(6, 19))
    world.react(local(6, 19), MessageKind.FLAT_POLL, reactor=ANNA)
    world.run(local(6, 19), local(7, 18))
    # The announcement is posted untracked, and the notice about it fails once.
    world.client.fail_sends(SendResponseUnreadable("{}"), delivered=True)
    world.client.fail_sends(ConnectionError("unreachable"))
    world.tick(local(7, 18))
    world.cancel(local(7, 18, 5))
    world.react(local(7, 18, 10))
    world.run(local(7, 18, 15), local(12, 0))

    assert world.dinner_texts() == ["ESSEN 18:00\n\nDINNER 18:00", CANCELLATION]
    assert Action.ANNOUNCEMENT_NOTICE not in world.outcomes()
    assert world.outcomes()[Action.TALLY] is Outcome.SKIPPED


# --- /status ------------------------------------------------------------------------------------


def status(world: World, now: datetime) -> list[str]:
    [reply] = run_command(world.store, "/status", now)
    return reply.splitlines()


def test_status_shows_an_open_request(world: World) -> None:
    world.run(local(5, 0), local(6, 19))
    world.cancel(local(6, 20))
    lines = status(world, local(6, 21))
    assert lines[3:5] == [
        "⏳ Entscheidung: Mi 18:00",
        "🛑 Absage per /cancel angefragt (Di 20:00) – wartet auf 👍",
    ]
    world.react(local(6, 21))
    lines = status(world, local(6, 21))
    assert lines[4] == "🛑 Absage per /cancel angefragt (Di 20:00) – bestätigt, geht gleich raus"
    assert lines[-1] == "Nächste Aktion: Absage an die Essensgruppe, gleich"


def test_status_of_a_week_cancelled_after_the_announcement(world: World) -> None:
    world.run(local(5, 0), local(6, 19))
    world.react(local(6, 19), MessageKind.FLAT_POLL, reactor=ANNA)
    world.run(local(6, 19), local(8, 9))
    world.cancel(local(8, 9))
    world.react(local(8, 9, 5))
    world.tick(local(8, 9, 15))

    assert status(world, local(8, 10)) == [
        "Sonntag, 11.10.",
        "✅ Frage an die WG gesendet (Di 18:00) – 1× 👍",
        "⏭️ Erinnerung: übersprungen",
        "✅ Einladung gesendet (Mi 18:00) – 0× 👍",
        "❌ Absage gesendet (Do 09:15) – per /cancel",
        "– Zählung: entfällt (kein Essen)",
        "Nächste Aktion: Frage an die WG, Di 18:00",
    ]


def test_status_of_a_week_cancelled_before_the_flat_ask(world: World) -> None:
    world.cancel(local(5, 10))
    world.react(local(5, 10, 5))
    world.tick(local(5, 10, 15))

    assert status(world, local(5, 11)) == [
        "Sonntag, 11.10.",
        "⏭️ Frage an die WG: übersprungen",
        "⏭️ Erinnerung: übersprungen",
        "❌ Absage gesendet (Mo 10:15) – per /cancel",
        "– Zählung: entfällt (kein Essen)",
        "Nächste Aktion: Frage an die WG, Di 18:00",
    ]
