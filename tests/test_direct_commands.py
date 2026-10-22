"""Chat commands in a direct message from a sender on `commands.direct_senders`."""

import asyncio
import logging
from datetime import date, datetime
from typing import Any

import pytest
from helpers import ms

from odin import commands
from odin.clock import FixedClock
from odin.commands import Command, CommandContext, ui
from odin.commands.help import GROUP_ONLY
from odin.config import Config, parse_config
from odin.engine import Account
from odin.events import consume_events
from odin.signal import DirectMessage, Event, FakeSignalClient
from odin.store import Action, MessageKind, Store

TEMPLATES = {
    "flat_ask": "Abendessen? {emoji} bis {deadline}",
    "nudge": "Noch kein {emoji}",
    "cancellation": "Abgesagt.\n\nCancelled.",
    "announcement": "Kochen {cook_time}, Essen {dinner_time}, {emoji} bis {rsvp_by}",
    "tally": "{count} mal {emoji}",
    "hello": "Hallo",
    "flat_test": "Test",
    "introduction": "Ich bin Odin.\n\nI am Odin.",
}

BOT = "+490000000000"
FLAT = "group.flat="
DINNER = "group.dinner="
ACCOUNT = Account(number=BOT, flat_group_id=FLAT, dinner_group_id=DINNER)
TIM = "+4915100000001"
TIM_UUID = "5c6a3e2b-1f0d-4c8e-9a7b-2d3e4f5a6b7c"
HIDDEN_UUID = "0f1e2d3c-4b5a-4968-8776-655443322110"
GUEST = "+4915100000009"

WEEK = date(2026, 10, 11)
NOW = datetime(2026, 10, 6, 18, 30, tzinfo=parse_config({"templates": TEMPLATES}).timezone)


def make_config(**commands_table: Any) -> Config:
    table = {"direct_senders": [TIM, HIDDEN_UUID], **commands_table}
    return parse_config({"templates": TEMPLATES, "commands": table})


def dm(
    text: str, sender: str = TIM, uuid: str | None = TIM_UUID, name: str | None = "Tim"
) -> DirectMessage:
    return DirectMessage(
        sender=sender, text=text, timestamp=ms(NOW), sender_uuid=uuid, sender_name=name
    )


class World:
    def __init__(self, store: Store, config: Config | None = None) -> None:
        self.store = store
        self.config = config or make_config()
        self.client = FakeSignalClient(number=BOT)

    def deliver(self, *events: Event) -> None:
        for event in events:
            self.client.inject(event)
        self.client.close()
        asyncio.run(consume_events(self.client, self.store, self.config, ACCOUNT, FixedClock(NOW)))

    def direct(self, recipient: str = TIM) -> list[str]:
        assert all(sent.recipient == recipient for sent in self.client.sent_direct)
        return [sent.text for sent in self.client.sent_direct]

    def flat(self) -> list[str]:
        assert all(sent.group_id == FLAT for sent in self.client.sent)
        return [sent.text for sent in self.client.sent]


@pytest.fixture
def world(store: Store) -> World:
    return World(store)


def test_a_command_from_an_allowed_number_is_answered_directly(world: World) -> None:
    world.deliver(dm("/schedule"))
    [reply] = world.direct()
    assert "Di 18:00" in reply
    assert world.client.sent == []


def test_a_command_from_an_allowed_uuid_only_sender_is_answered_directly(world: World) -> None:
    world.deliver(dm("/status", sender=HIDDEN_UUID, uuid=HIDDEN_UUID, name=None))
    assert len(world.direct(HIDDEN_UUID)) == 1
    assert world.client.sent == []


def test_an_allowed_uuid_matches_a_sender_whose_number_is_visible(store: Store) -> None:
    commands_table = {"direct_senders": [TIM_UUID.upper()]}
    world = World(store, parse_config({"templates": TEMPLATES, "commands": commands_table}))
    world.deliver(dm("/version"))
    assert len(world.direct(TIM)) == 1


@pytest.mark.parametrize("text", ["/help", "/settime tally fri 15:00", "Hallo?"])
def test_a_sender_not_on_the_list_gets_nothing(
    world: World, text: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="odin.events")
    world.deliver(dm(text, sender=GUEST, uuid=HIDDEN_UUID.replace("0", "a"), name="Gast"))
    assert world.client.sent_direct == []
    assert world.client.sent == []
    assert world.store.overrides() == {}
    assert GUEST in caplog.text
    assert HIDDEN_UUID.replace("0", "a") in caplog.text


def test_the_bots_own_number_gets_nothing(world: World) -> None:
    world.deliver(dm("/settime tally fri 15:00", sender=BOT, uuid=None))
    assert world.client.sent_direct == []
    assert world.client.sent == []
    assert world.store.overrides() == {}


def test_with_an_empty_list_direct_messages_are_ignored(store: Store) -> None:
    world = World(store, parse_config({"templates": TEMPLATES}))
    world.deliver(dm("/help"), dm("/settime tally fri 15:00"), dm("Hallo"))
    assert world.client.sent_direct == []
    assert world.client.sent == []
    assert world.store.overrides() == {}


def test_a_message_that_is_not_a_command_gets_the_hint(world: World) -> None:
    world.deliver(dm("Hallo Odin"))
    assert world.direct() == [ui.DIRECT_NOT_A_COMMAND]
    assert world.client.sent == []


def test_an_unknown_command_gets_the_usual_hint(world: World) -> None:
    world.deliver(dm("/hilfe"))
    assert world.direct() == [ui.UNKNOWN_COMMAND.format(command="/hilfe")]
    assert world.client.sent == []


def test_a_change_takes_effect_and_is_told_to_the_flat_group_once(world: World) -> None:
    world.deliver(dm("/settime tally fri 15:00"))
    override = world.store.overrides()["schedule.tally"]
    assert (override.value, override.changed_by) == ("fri 15:00", "Tim")
    assert len(world.direct()) == 1
    assert world.flat() == [ui.DIRECT_NOTICE.format(name="Tim", command="/settime tally fri 15:00")]


def test_the_notice_names_a_sender_without_a_name_by_their_id(world: World) -> None:
    world.deliver(dm("/nudge off", sender=HIDDEN_UUID, uuid=HIDDEN_UUID, name=None))
    assert world.flat() == [ui.DIRECT_NOTICE.format(name=HIDDEN_UUID, command="/nudge off")]


def test_the_notice_quotes_only_the_first_line(world: World) -> None:
    world.deliver(dm("/settext tally\n{count} Leute kommen"))
    assert world.store.overrides()["templates.tally"].value == "{count} Leute kommen"
    assert world.flat() == [ui.DIRECT_NOTICE.format(name="Tim", command="/settext tally")]


def test_with_the_notice_off_a_change_posts_nothing_to_the_flat_group(store: Store) -> None:
    world = World(store, make_config(direct_notice=False))
    world.deliver(dm("/settime tally fri 15:00"))
    assert world.store.overrides()["schedule.tally"].value == "fri 15:00"
    assert len(world.direct()) == 1
    assert world.client.sent == []


def test_a_refused_change_posts_no_notice(world: World) -> None:
    world.deliver(dm("/settime tally sat 25:00"), dm("/unskip 2026-10-18"))
    assert len(world.direct()) == 2
    assert world.store.overrides() == {}
    assert world.client.sent == []


def test_a_changing_command_that_only_reads_posts_no_notice(world: World) -> None:
    world.deliver(dm("/skip"))
    assert len(world.direct()) == 1
    assert world.client.sent == []


READ_ONLY = ["/help", "/status", "/schedule", "/texts", "/text tally", "/vars", "/version"]


@pytest.mark.parametrize("notice", [True, False])
@pytest.mark.parametrize("text", READ_ONLY)
def test_a_read_only_command_never_posts_a_notice(store: Store, text: str, notice: bool) -> None:
    world = World(store, make_config(direct_notice=notice))
    world.deliver(dm(text))
    assert world.direct()
    assert world.client.sent == []


def test_read_only_commands_are_not_marked_as_changing() -> None:
    names = {command.name for command in commands.COMMANDS if command.changes}
    assert names.isdisjoint(text.split()[0][1:] for text in READ_ONLY)


@pytest.mark.parametrize("text", ["/cancel", "/hiatus", "/introduce"])
def test_commands_that_need_a_confirmation_are_refused(world: World, text: str) -> None:
    world.deliver(dm(text))
    assert world.direct() == [ui.DIRECT_GROUP_ONLY.format(command=text, emoji="👍")]
    assert world.client.sent == []
    for kind in MessageKind:
        assert world.store.tracked_messages(kind) == []
    assert world.store.hiatus_request(WEEK) is None
    assert world.store.hiatuses() == []


def test_skipping_the_running_week_is_refused_like_cancel(world: World) -> None:
    world.store.record_action(WEEK, Action.FLAT_ASK, NOW)
    world.deliver(dm("/skip 2026-10-11"))
    assert world.direct() == [ui.DIRECT_GROUP_ONLY.format(command="/skip 2026-10-11", emoji="👍")]
    assert world.client.sent == []
    assert world.store.tracked_messages(MessageKind.CANCEL_REQUEST) == []
    assert world.store.skip_date(WEEK) is None


def test_help_in_a_direct_message_names_the_group_only_commands(world: World) -> None:
    world.deliver(dm("/help"))
    [reply] = world.direct()
    assert reply.endswith(GROUP_ONLY.format(commands="/cancel, /introduce, /hiatus"))


def test_help_in_the_flat_group_does_not(store: Store) -> None:
    ctx = CommandContext(make_config(), make_config(), store, NOW, TIM, "Tim")
    [reply] = commands.handle("/help", ctx)
    assert "Nur in der WG-Gruppe" not in reply


def test_a_crashing_command_gets_the_generic_error_as_a_direct_message(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(ctx: CommandContext, args: str) -> list[str]:
        raise RuntimeError("boom")

    crash = Command("crash", "/crash", "Test.", run, changes=True)
    monkeypatch.setattr(commands, "COMMANDS", [*commands.COMMANDS, crash])
    world.deliver(dm("/crash"), dm("/version"))
    assert world.direct()[0] == ui.GENERIC_ERROR
    assert len(world.direct()) == 2
    assert world.client.sent == []


def test_a_long_command_line_is_shortened_in_the_notice(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(ctx: CommandContext, args: str) -> list[str]:
        ctx.store.set_setting("test", args)
        return ["ok"]

    note = Command("note", "/note <text>", "Test.", run, changes=True)
    monkeypatch.setattr(commands, "COMMANDS", [*commands.COMMANDS, note])
    world.deliver(dm("/note " + "x" * 200))
    [notice] = world.flat()
    assert notice.endswith("…")
    assert len(notice) < len(ui.DIRECT_NOTICE) + commands.NOTICE_LENGTH
