"""/introduce end to end: the command, its tracked reply, the confirming reaction and the engine."""

import asyncio
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from helpers import local, ms

from odin.clock import FixedClock
from odin.commands import CommandContext, TrackedReply, handle, ui
from odin.commands.introduce import USAGE
from odin.config import Config, parse_config
from odin.engine import Account, SendFailure, reconcile
from odin.events import consume_events
from odin.overrides import effective_config
from odin.signal import FakeSignalClient, GroupMessage, ReactionEvent, SendResponseUnreadable
from odin.store import Action, MessageKind, Outcome, Store, TrackedMessage

WEEKLY = {
    "flat_ask": "ASK {emoji} bis {deadline}",
    "nudge": "NUDGE {deadline}",
    "cancellation": "ABGESAGT {dinner_day_de}\n\nCANCELLED {dinner_day_en}",
    "announcement": "ESSEN {dinner_time}\n\nDINNER {dinner_time}",
    "tally": "TALLY {count} x {emoji}",
    "hello": "HELLO",
    "flat_test": "TEST",
}
TEMPLATES = WEEKLY | {
    "introduction": "HALLO {dinner_day_de} {rsvp_by_day_de} {rsvp_by}\n\n"
    "HELLO {dinner_day_en} {rsvp_by_day_en} {rsvp_by}",
}
# Default schedule: ask Tue 18:00, nudge Wed 12:00, decision Wed 18:00, tally Fri 14:00,
# dinner Sun 18:00.
CONFIG = parse_config({"templates": TEMPLATES})
WITHOUT_INTRODUCTION = parse_config({"templates": WEEKLY})

BOT = "+490000000000"
FLAT, DINNER = "group.flat=", "group.dinner="
ACCOUNT = Account(number=BOT, flat_group_id=FLAT, dinner_group_id=DINNER)
ANNA, BEN = "+4915100000001", "+4915100000002"

WEEK = date(2026, 10, 11)
INTRODUCTION = "HALLO Sonntag Freitag 14:00\n\nHELLO Sunday Friday 14:00"


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
        config = effective_config(self.config, self.store, now)
        asyncio.run(reconcile(config, self.store, self.client, ACCOUNT, now, self.failures))

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
        asyncio.run(consume_events(self.client, self.store, self.config, ACCOUNT, clock))
        return [sent.text for sent in self.client.sent[before:]]

    def say(self, now: datetime, text: str) -> list[str]:
        return self.chat(now, message(text, now))

    def introduce(self, now: datetime) -> list[str]:
        return self.say(now, "/introduce")

    def request(self) -> TrackedMessage:
        [request] = self.store.tracked_messages(MessageKind.INTRODUCTION_REQUEST)
        return request

    def react(
        self,
        now: datetime,
        target: TrackedMessage | None = None,
        *,
        reactor: str = BEN,
        emoji: str = "👍",
        remove: bool = False,
    ) -> None:
        target = target or self.request()
        event = ReactionEvent(
            emoji=emoji,
            reactor=reactor,
            target_author=target.author,
            target_timestamp=target.timestamp,
            group_id=target.group_id,
            is_remove=remove,
            timestamp=ms(now),
        )
        self.chat(now, event)

    def dinner_texts(self) -> list[str]:
        return [sent.text for sent in self.client.sent if sent.group_id == DINNER]


def message(text: str, now: datetime, group: str = FLAT) -> GroupMessage:
    return GroupMessage(
        sender=ANNA, sender_name="Anna", text=text, group_id=group, timestamp=ms(now)
    )


@pytest.fixture
def world(store: Store) -> World:
    return World(store)


def run_command(store: Store, text: str, now: datetime, config: Config = CONFIG) -> list[str]:
    ctx = CommandContext(
        base=config, config=config, store=store, now=now, sender=ANNA, sender_name="Anna"
    )
    return handle(text, ctx)


# --- The command --------------------------------------------------------------------------------


def test_introduce_asks_for_confirmation_and_shows_the_introduction(store: Store) -> None:
    [reply] = run_command(store, "/introduce", local(5, 10))
    assert isinstance(reply, TrackedReply)
    assert (reply.week, reply.kind) == (WEEK, MessageKind.INTRODUCTION_REQUEST)
    assert reply == (
        "Soll ich mich der Essensgruppe vorstellen? Dann reagiert mit 👍 auf diese Nachricht – "
        "ich schicke der Essensgruppe dann diesen Text:\n"
        "Ohne 👍 passiert nichts; die Anfrage verfällt am Di 06.10. 10:00 oder mit dem nächsten "
        f"/introduce.\n\n{INTRODUCTION}"
    )
    # The command itself writes nothing.
    assert store.tracked_messages(MessageKind.INTRODUCTION_REQUEST) == []


def test_the_lapse_is_24_hours_also_across_a_dst_change(store: Store) -> None:
    [reply] = run_command(store, "/introduce", local(24, 10))  # clocks go back on 25 Oct
    assert "die Anfrage verfällt am So 25.10. 09:00" in reply


def test_introduce_takes_no_arguments(store: Store) -> None:
    assert run_command(store, "/introduce now", local(5, 10)) == [USAGE]


def test_without_a_text_it_asks_for_one(store: Store) -> None:
    assert run_command(store, "!Introduce", local(5, 10), WITHOUT_INTRODUCTION) == [
        "introduction ist nicht gesetzt. Anlegen: /settext introduction – und in den Zeilen "
        "darunter der Text."
    ]


def test_listed_in_help(store: Store) -> None:
    [reply] = run_command(store, "/help", local(5, 10))
    assert "/introduce – Stellt Odin der Essensgruppe vor – nach Bestätigung per Reaktion." in (
        reply.splitlines()
    )


def test_ignored_in_the_dinner_group(world: World) -> None:
    now = local(5, 10)
    assert world.chat(now, message("/introduce", now, group=DINNER)) == []
    world.run(now, local(5, 12))
    assert world.client.sent == []
    assert world.store.tracked_messages(MessageKind.INTRODUCTION_REQUEST) == []


# --- Tracking the request -----------------------------------------------------------------------


def test_the_reply_is_tracked_and_nothing_is_posted_yet(world: World) -> None:
    [reply] = world.introduce(local(5, 10))
    request = world.request()
    assert (request.week, request.group_id, request.author) == (WEEK, FLAT, BOT)
    [sent] = world.client.sent
    assert (sent.group_id, sent.text, sent.timestamp) == (FLAT, reply, request.timestamp)
    world.run(local(5, 10), local(5, 12))
    assert world.dinner_texts() == []


def test_a_new_request_replaces_the_open_one(world: World) -> None:
    world.introduce(local(5, 10))
    first = world.request()
    world.react(local(5, 10, 1), reactor=ANNA)  # on the old one, but replaced before the tick
    world.introduce(local(5, 10, 2))
    second = world.request()
    assert second != first
    world.react(local(5, 10, 3), first)  # ignored: no longer tracked
    world.run(local(5, 10, 5), local(5, 12))
    assert world.dinner_texts() == []

    world.react(local(5, 12), second)
    world.tick(local(5, 12, 1))
    assert world.dinner_texts() == [INTRODUCTION]


def test_an_unreadable_send_leaves_the_request_untracked(world: World) -> None:
    world.client.fail_sends(SendResponseUnreadable("{}"), delivered=True)
    world.introduce(local(5, 10))
    assert world.store.tracked_messages(MessageKind.INTRODUCTION_REQUEST) == []
    world.introduce(local(5, 11))
    assert world.request() is not None


# --- The engine ---------------------------------------------------------------------------------


def test_confirmed_it_is_posted_once(world: World) -> None:
    world.introduce(local(5, 10))
    world.react(local(5, 10, 5))
    world.react(local(5, 10, 6), reactor=ANNA)  # a second 👍 changes nothing
    world.run(local(5, 10, 15), local(6, 12))
    world.react(local(6, 12), reactor=ANNA, remove=True)
    world.react(local(6, 12), reactor=ANNA)
    world.run(local(6, 12), local(6, 14))

    assert world.dinner_texts() == [INTRODUCTION]
    assert world.store.introduction_time(world.request()) == local(5, 10, 15)


def test_posted_once_across_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "odin.db"
    with Store(path) as store:
        world = World(store)
        world.introduce(local(5, 10))
        world.react(local(5, 10, 5))
        world.tick(local(5, 10, 15))
        assert world.dinner_texts() == [INTRODUCTION]
    with Store(path) as store:
        restarted = World(store)
        restarted.run(local(5, 10, 30), local(5, 12))
        assert restarted.dinner_texts() == []


def test_a_later_request_posts_it_again(world: World) -> None:
    world.introduce(local(5, 10))
    world.react(local(5, 10, 5))
    world.tick(local(5, 10, 15))

    [reply] = world.introduce(local(9, 19))
    assert reply.splitlines()[2] == "Zuletzt vorgestellt: Mo 05.10. 10:15."
    world.run(local(9, 19), local(9, 20))
    assert world.dinner_texts() == [INTRODUCTION]  # not without its own confirmation
    world.react(local(9, 20))
    world.tick(local(9, 20, 1))
    assert world.dinner_texts() == [INTRODUCTION, INTRODUCTION]


def test_without_confirmation_nothing_is_posted(world: World) -> None:
    world.introduce(local(5, 10))
    world.react(local(5, 10, 5), emoji="❤️")  # another emoji does not confirm
    world.react(local(5, 10, 6), reactor=ANNA)
    world.react(local(5, 10, 7), reactor=ANNA, remove=True)  # withdrawn before the tick
    world.run(local(5, 10, 15), local(7, 12))
    assert world.dinner_texts() == []


def test_a_request_lapses_after_a_day(world: World) -> None:
    world.introduce(local(5, 10))
    world.react(local(6, 10))  # 24 hours later: too late
    world.run(local(6, 10), local(6, 12))
    assert world.dinner_texts() == []


def test_confirmed_just_in_time_it_is_posted(world: World) -> None:
    world.introduce(local(5, 10))
    world.react(local(6, 9, 59))
    world.tick(local(6, 10, 5))  # the tick may come after the lapse
    assert world.dinner_texts() == [INTRODUCTION]


def test_a_failed_send_is_retried_and_posted_once(world: World) -> None:
    world.introduce(local(5, 10))
    world.react(local(5, 10, 5))
    world.client.fail_sends(ConnectionError("unreachable"))
    world.tick(local(5, 10, 15))
    assert world.dinner_texts() == []
    assert world.failures == [SendFailure(WEEK, Action.INTRODUCTION, "ConnectionError")]
    world.run(local(5, 10, 30), local(5, 12))
    assert world.dinner_texts() == [INTRODUCTION]


def test_an_unreadable_response_counts_as_posted(world: World) -> None:
    world.introduce(local(5, 10))
    world.react(local(5, 10, 5))
    world.client.fail_sends(SendResponseUnreadable("{}"), delivered=True)
    world.run(local(5, 10, 15), local(5, 12))
    assert world.dinner_texts() == [INTRODUCTION]


def test_a_text_taken_back_after_the_request_is_not_posted(
    store: Store, caplog: pytest.LogCaptureFixture
) -> None:
    world = World(store, WITHOUT_INTRODUCTION)
    world.say(local(5, 9), "/settext introduction\nHALLO\n\nHELLO")
    world.introduce(local(5, 10))
    world.react(local(5, 10, 5))
    world.say(local(5, 10, 6), "/resettext introduction")
    with caplog.at_level(logging.WARNING):
        world.run(local(5, 10, 15), local(5, 12))
    assert world.dinner_texts() == []
    assert world.store.tracked_messages(MessageKind.INTRODUCTION_REQUEST) == []
    assert caplog.text.count("its template is not set") == 1


def test_the_weekly_cycle_is_not_touched(world: World) -> None:
    world.introduce(local(5, 10))
    world.react(local(5, 10, 5))
    world.run(local(5, 10, 15), local(12, 0))  # nobody confirms the flat poll

    assert world.dinner_texts() == [INTRODUCTION, "ABGESAGT Sonntag\n\nCANCELLED Sunday"]
    outcomes = {action: world.store.action_outcome(WEEK, action) for action in Action}
    assert outcomes[Action.INTRODUCTION] is None
    assert outcomes[Action.FLAT_ASK] is Outcome.SENT
    [reply] = run_command(world.store, "/status", local(12, 1))
    assert "introduc" not in reply.lower()
    assert "Vorstell" not in reply


# --- The template -------------------------------------------------------------------------------


def test_listed_by_texts(store: Store) -> None:
    [reply] = run_command(store, "/texts", local(5, 10))
    assert "introduction (Essensgruppe) – Vorstellung von Odin, per /introduce" in (
        reply.splitlines()
    )


def test_text_of_an_unset_introduction(store: Store) -> None:
    assert run_command(store, "/text introduction", local(5, 10), WITHOUT_INTRODUCTION) == [
        ui.NOT_SET.format(name="introduction")
    ]


def test_editable_with_settext(store: Store) -> None:
    world = World(store, WITHOUT_INTRODUCTION)
    saved = world.say(local(5, 9), "/settext introduction\nHallo am {dinner_day_de}\n\nHi")
    assert saved == [
        "Gespeichert ✅ So sieht introduction jetzt aus:",
        "Hallo am Sonntag\n\nHi",
    ]
    [reply] = world.introduce(local(5, 10))
    assert reply.endswith("\n\nHallo am Sonntag\n\nHi")
    world.react(local(5, 10, 5))
    world.tick(local(5, 10, 15))
    assert world.dinner_texts() == ["Hallo am Sonntag\n\nHi"]

    assert world.say(local(5, 11), "/resettext introduction") == [
        "Zurückgesetzt ✅ introduction ist jetzt nicht gesetzt."
    ]
