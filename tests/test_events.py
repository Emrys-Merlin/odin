import asyncio
from collections.abc import Iterator
from datetime import date, datetime

import pytest

from odin import commands
from odin.clock import FixedClock
from odin.commands import Command, CommandContext, CommandError, ui
from odin.config import Config, parse_config
from odin.engine import Account
from odin.events import consume_events
from odin.signal import Event, FakeSignalClient, GroupMessage, ReactionEvent
from odin.store import MessageKind, Store

TEMPLATES = {
    "flat_ask": "Abendessen? {emoji} bis {deadline}",
    "nudge": "Noch kein {emoji}",
    "cancellation": "Abgesagt.\n\nCancelled.",
    "announcement": "Kochen {cook_time}, Essen {dinner_time}, {emoji} bis {rsvp_by}",
    "tally": "{count} mal {emoji}",
    "hello": "Hallo",
    "flat_test": "Test",
}
CONFIG: Config = parse_config({"templates": TEMPLATES})
BERLIN = CONFIG.timezone

BOT = "+490000000000"
FLAT = "group.flat="
DINNER = "group.dinner="
ACCOUNT = Account(number=BOT, flat_group_id=FLAT, dinner_group_id=DINNER)
ANNA = "+4915100000001"

WEEK = date(2026, 10, 11)
NOW = datetime(2026, 10, 6, 18, 30, tzinfo=BERLIN)


def ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def message(text: str, group_id: str = FLAT, sender: str = ANNA) -> GroupMessage:
    return GroupMessage(
        sender=sender, sender_name="Anna", text=text, group_id=group_id, timestamp=ms(NOW)
    )


class World:
    def __init__(self, store: Store, client: FakeSignalClient | None = None) -> None:
        self.store = store
        self.client = client or FakeSignalClient(number=BOT)
        self.clock = FixedClock(NOW)

    def deliver(self, *events: Event) -> None:
        """Run the consumer over exactly these events: closing ends the stream."""
        for event in events:
            self.client.inject(event)
        self.client.close()
        asyncio.run(consume_events(self.client, self.store, CONFIG, ACCOUNT, self.clock))

    def replies(self) -> list[str]:
        assert all(sent.group_id == FLAT for sent in self.client.sent)
        return [sent.text for sent in self.client.sent]


@pytest.fixture
def store() -> Iterator[Store]:
    with Store(":memory:") as s:
        yield s


@pytest.fixture
def world(store: Store) -> World:
    return World(store)


def register(monkeypatch: pytest.MonkeyPatch, *extra: Command) -> None:
    monkeypatch.setattr(commands, "COMMANDS", [*commands.COMMANDS, *extra])


def test_help_in_the_flat_group_is_answered_there(world: World) -> None:
    world.deliver(message("/help"))
    [reply] = world.replies()
    assert reply.startswith("Das kann ich:")
    assert "/help" in reply


def test_commands_in_the_dinner_group_are_ignored(world: World) -> None:
    world.deliver(message("/help", group_id=DINNER), message("/nonsense", group_id=DINNER))
    assert world.client.sent == []


def test_commands_in_an_unknown_group_are_ignored(world: World) -> None:
    world.deliver(message("/help", group_id="group.other="))
    assert world.client.sent == []


def test_the_bots_own_messages_are_ignored(world: World) -> None:
    world.deliver(message("/help", sender=BOT), message("/settext tally\n{count}", sender=BOT))
    assert world.client.sent == []


def test_plain_messages_get_no_reply(world: World) -> None:
    world.deliver(message("Ich bringe Nachtisch mit"), message("/ 2 Leute"), message("👍"))
    assert world.client.sent == []


def test_unknown_command_gets_the_hint(world: World) -> None:
    world.deliver(message("/frobnicate"))
    assert world.replies() == [ui.UNKNOWN_COMMAND.format(command="/frobnicate")]


def test_context_carries_sender_time_and_both_configs(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[CommandContext] = []

    def run(ctx: CommandContext, args: str) -> list[str]:
        seen.append(ctx)
        return [f"args={args}"]

    world.store.set_override("templates.nudge", "Wer kommt?", "Tim", NOW)
    register(monkeypatch, Command("peek", "/peek", "Test.", run))
    world.deliver(message("!PEEK a b"))

    [ctx] = seen
    assert (ctx.sender, ctx.sender_name, ctx.now) == (ANNA, "Anna", NOW)
    assert ctx.store is world.store
    assert ctx.base is CONFIG
    assert ctx.config.templates.nudge.text == "Wer kommt?"
    assert world.replies() == ["args=a b"]


def test_replies_are_sent_in_order(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    register(monkeypatch, Command("many", "/many", "Test.", lambda ctx, args: ["1", "2", "3"]))
    world.deliver(message("/many"), message("/many"))
    assert world.replies() == ["1", "2", "3", "1", "2", "3"]


def test_command_error_is_the_reply(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    def run(ctx: CommandContext, args: str) -> list[str]:
        raise CommandError("Das geht so nicht.")

    register(monkeypatch, Command("refuse", "/refuse", "Test.", run))
    world.deliver(message("/refuse"))
    assert world.replies() == ["Das geht so nicht."]


def test_a_crashing_command_gets_the_generic_error_and_the_consumer_survives(
    world: World, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def run(ctx: CommandContext, args: str) -> list[str]:
        raise RuntimeError("boom")

    register(monkeypatch, Command("crash", "/crash", "Test.", run))
    poll = world.store.track_message(WEEK, MessageKind.FLAT_POLL, FLAT, BOT, ms(NOW) - 1)
    reaction = ReactionEvent(
        emoji="👍",
        reactor=ANNA,
        target_author=poll.author,
        target_timestamp=poll.timestamp,
        group_id=FLAT,
        is_remove=False,
        timestamp=ms(NOW),
    )

    world.deliver(message("/crash"), reaction, message("/help"))

    assert world.replies()[0] == ui.GENERIC_ERROR
    assert [r.reactor for r in world.store.reactions_for(poll)] == [ANNA]
    assert world.replies()[1].startswith("Das kann ich:")
    assert "boom" in caplog.text


def test_a_failed_reply_is_logged_and_not_retried(
    store: Store, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class FailFirst(FakeSignalClient):
        failed = False

        async def send_group_message(self, group_id: str, text: str) -> int:
            if not self.failed:
                self.failed = True
                raise ConnectionError("signal-cli-rest-api unreachable")
            return await super().send_group_message(group_id, text)

    world = World(store, FailFirst(number=BOT))
    register(monkeypatch, Command("two", "/two", "Test.", lambda ctx, args: ["eins", "zwei"]))
    world.deliver(message("/two"), message("/two"))

    assert world.replies() == ["zwei", "eins", "zwei"]
    assert "command reply failed" in caplog.text
