"""The cook emoji: 🍳 on the dinner announcement means "I'm coming and I'll help cook".

Covers the config key, counting (`count_guests`), the tally's `{cooks}`, the emojis recorded per
tracked message (so an `/emoji` change applies from the next message on) and the migration.
"""

import asyncio
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from helpers import local, ms

from odin.clock import FixedClock
from odin.commands import ui
from odin.config import ConfigError, parse_config
from odin.engine import Account, reconcile
from odin.events import consume_events
from odin.overrides import COOK_EMOJI_KEY, EMOJI_KEY, apply_overrides, effective_config
from odin.reactions import Guests, count_confirmations, count_guests
from odin.signal import FakeSignalClient, GroupMessage, ReactionEvent
from odin.store import MessageKind, Store

TEMPLATES = {
    "flat_ask": "ASK {emoji}",
    "nudge": "NUDGE",
    "cancellation": "ABGESAGT\n\nCANCELLED",
    "announcement": "ESSEN {emoji} {cook_emoji}\n\nDINNER {emoji} {cook_emoji}",
    "tally": "TALLY {count} davon {cooks}",
    "hello": "HELLO",
    "flat_test": "TEST",
}
CONFIG = parse_config({"templates": TEMPLATES})

BOT = "+490000000000"
FLAT, DINNER = "group.flat=", "group.dinner="
ACCOUNT = Account(number=BOT, flat_group_id=FLAT, dinner_group_id=DINNER)
ANNA, BEN, CARL, DORA, EVA = (f"+491510000000{i}" for i in range(1, 6))

# Default schedule: ask Tue 06.10. 18:00, decision Wed 07.10. 18:00, tally Fri 09.10. 14:00,
# dinner Sun 11.10. 18:00.
WEEK = date(2026, 10, 11)


# --- Config -------------------------------------------------------------------------------------


def test_cook_emoji_defaults_to_the_frying_pan() -> None:
    assert CONFIG.cook_emoji == "🍳"
    assert CONFIG.placeholder_values()["cook_emoji"] == "🍳"


def test_cook_emoji_can_be_set() -> None:
    config = parse_config({"templates": TEMPLATES, "cook_emoji": " 🧑‍🍳 "})
    assert config.cook_emoji == "🧑‍🍳"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"cook_emoji": "👍"}, "must differ from emoji"),
        ({"cook_emoji": "👍🏽"}, "must differ from emoji"),  # a skin tone is the same reaction
        ({"emoji": "🍳"}, "must differ from emoji"),
        ({"cook_emoji": ""}, "non-empty"),
        ({"cook_emoji": "cook"}, "single emoji"),
        ({"cook_emoji": "🍳 🔪"}, "single emoji"),
        ({"emoji": "+1"}, "single emoji"),
    ],
)
def test_invalid_emojis_are_rejected(data: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_config({"templates": TEMPLATES, **data})


def test_cooks_is_a_tally_placeholder_only() -> None:
    with pytest.raises(ConfigError, match="cooks"):
        parse_config({"templates": TEMPLATES | {"announcement": "{cooks}\n\n{cooks}"}})


def test_emoji_overrides_are_validated_together() -> None:
    config = apply_overrides(CONFIG, {EMOJI_KEY: "🙋", COOK_EMOJI_KEY: "🔪"})
    assert (config.emoji, config.cook_emoji) == ("🙋", "🔪")
    with pytest.raises(ConfigError, match="must differ"):
        apply_overrides(CONFIG, {COOK_EMOJI_KEY: "👍"})
    with pytest.raises(ConfigError, match="single emoji"):
        apply_overrides(CONFIG, {EMOJI_KEY: "yes"})


# --- Counting -----------------------------------------------------------------------------------


def _react(store: Store, message, reactor: str, emoji: str) -> None:
    store.set_reaction(message, reactor, emoji, local(8, 9))


def test_the_cook_emoji_counts_as_coming_and_cooking(store: Store) -> None:
    announcement = store.track_message(WEEK, MessageKind.DINNER_ANNOUNCEMENT, DINNER, BOT, 1)
    _react(store, announcement, ANNA, "👍")
    _react(store, announcement, BEN, "🍳")
    _react(store, announcement, CARL, "🍳️")  # with a variation selector
    _react(store, announcement, DORA, "❤️")
    assert count_guests(store, announcement, CONFIG) == Guests(count=3, cooks=2)
    assert ui.guests(store, announcement, CONFIG) == "3 kommen (1× 👍, 2× 🍳)"


def test_the_cook_emoji_does_not_confirm_the_flat_poll(store: Store) -> None:
    poll = store.track_message(WEEK, MessageKind.FLAT_POLL, FLAT, BOT, 1)
    _react(store, poll, ANNA, "🍳")
    assert count_confirmations(store, poll, CONFIG) == 0
    _react(store, poll, BEN, "👍")
    assert count_confirmations(store, poll, CONFIG) == 1


def test_a_message_counts_the_emojis_it_was_sent_with(store: Store) -> None:
    announcement = store.track_message(
        WEEK, MessageKind.DINNER_ANNOUNCEMENT, DINNER, BOT, 1, emoji="🙋", cook_emoji="🔪"
    )
    _react(store, announcement, ANNA, "🙋")
    _react(store, announcement, BEN, "🔪")
    _react(store, announcement, CARL, "👍")  # the configured emojis do not count here
    _react(store, announcement, DORA, "🍳")
    assert count_guests(store, announcement, CONFIG) == Guests(count=2, cooks=1)
    assert ui.guests(store, announcement, CONFIG) == "2 kommen (1× 🙋, 1× 🔪)"


def test_an_untracked_announcement_names_both_emojis() -> None:
    assert ui.guests(Store(":memory:"), None, CONFIG) == "👍/🍳 nicht zählbar"


# --- The week, end to end -----------------------------------------------------------------------


class Client(FakeSignalClient):
    """Sent messages get the Signal timestamp of `now`, as on Signal."""

    now: datetime | None = None

    async def send_group_message(self, group_id: str, text: str) -> int:
        if self.now is not None:
            self._next_timestamp = max(self._next_timestamp, ms(self.now))
        return await super().send_group_message(group_id, text)


class World:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.client = Client(number=BOT)

    def run(self, start: datetime, end: datetime) -> None:
        now = start
        while now < end:
            self.client.now = now
            config = effective_config(CONFIG, self.store, now)
            asyncio.run(reconcile(config, self.store, self.client, ACCOUNT, now))
            now += timedelta(minutes=15)

    def chat(self, now: datetime, *events: GroupMessage | ReactionEvent) -> list[str]:
        self.client.now = now
        before = len(self.client.sent)
        for event in events:
            self.client.inject(event)
        self.client.close()
        asyncio.run(consume_events(self.client, self.store, CONFIG, ACCOUNT, FixedClock(now)))
        return [sent.text for sent in self.client.sent[before:]]

    def command(self, now: datetime, text: str) -> list[str]:
        return self.chat(
            now,
            GroupMessage(sender=ANNA, sender_name="Anna", text=text, group_id=FLAT, timestamp=1),
        )

    def react(self, now: datetime, kind: MessageKind, reactor: str, emoji: str) -> None:
        tracked = self.store.tracked_message(WEEK, kind)
        assert tracked is not None, f"{kind} not tracked"
        event = ReactionEvent(
            emoji=emoji,
            reactor=reactor,
            target_author=tracked.author,
            target_timestamp=tracked.timestamp,
            group_id=tracked.group_id,
            is_remove=False,
            timestamp=ms(now),
        )
        self.chat(now, event)

    def texts(self, group: str) -> list[str]:
        return [sent.text for sent in self.client.sent if sent.group_id == group]


@pytest.fixture
def world(store: Store) -> World:
    return World(store)


def test_the_tally_counts_the_cooks(world: World) -> None:
    world.run(local(6, 17), local(6, 18, 15))
    world.react(local(6, 19), MessageKind.FLAT_POLL, ANNA, "👍")
    world.run(local(6, 18, 15), local(7, 18, 15))
    assert world.texts(DINNER) == ["ESSEN 👍 🍳\n\nDINNER 👍 🍳"]
    for reactor, emoji in ((BEN, "👍"), (CARL, "🍳"), (DORA, "🍳"), (EVA, "❤️")):
        world.react(local(8, 10), MessageKind.DINNER_ANNOUNCEMENT, reactor, emoji)
    world.run(local(9, 14), local(9, 14, 15))
    assert world.texts(FLAT)[-1] == "TALLY 3 davon 2"


def test_an_emoji_change_applies_from_the_next_message_on(world: World) -> None:
    world.run(local(6, 17), local(6, 18, 15))
    poll = world.store.tracked_message(WEEK, MessageKind.FLAT_POLL)
    assert poll is not None
    assert (poll.emoji, poll.cook_emoji) == ("👍", "🍳")

    # Changed after the flat ask: the flat poll still counts 👍, which it asked for.
    world.command(local(6, 19), "/emoji attend 🙋")
    world.react(local(6, 19, 5), MessageKind.FLAT_POLL, ANNA, "👍")
    world.run(local(6, 18, 15), local(7, 18, 15))
    announcement = world.store.tracked_message(WEEK, MessageKind.DINNER_ANNOUNCEMENT)
    assert announcement is not None
    assert (announcement.emoji, announcement.cook_emoji) == ("🙋", "🍳")
    assert world.texts(DINNER) == ["ESSEN 🙋 🍳\n\nDINNER 🙋 🍳"]

    # Changed after the announcement: it keeps counting 🍳.
    world.command(local(8, 9), "/emoji cook 🔪")
    world.react(local(8, 10), MessageKind.DINNER_ANNOUNCEMENT, BEN, "🙋")
    world.react(local(8, 10), MessageKind.DINNER_ANNOUNCEMENT, CARL, "🍳")
    world.react(local(8, 10), MessageKind.DINNER_ANNOUNCEMENT, DORA, "🔪")
    world.run(local(9, 14), local(9, 14, 15))
    assert world.texts(FLAT)[-1] == "TALLY 2 davon 1"


def test_a_command_reply_is_tracked_with_the_emojis_in_effect(world: World) -> None:
    world.store.set_override("templates.introduction", "HI\n\nHI", "Anna", local(6, 9))
    world.command(local(6, 9), "/emoji attend 🙋")
    world.command(local(6, 10), "/introduce")
    [request] = world.store.tracked_messages(MessageKind.INTRODUCTION_REQUEST)
    assert request.emoji == "🙋"


# --- Store --------------------------------------------------------------------------------------


def test_upgrade_from_version_10_keeps_counting_with_the_configured_emojis(
    tmp_path: Path,
) -> None:
    from odin.store import _MIGRATIONS

    path = tmp_path / "odin.db"
    conn = sqlite3.connect(path)
    conn.executescript(f"{'; '.join(_MIGRATIONS[:10])}; PRAGMA user_version = 10;")
    conn.execute(
        "INSERT INTO messages VALUES ('2026-10-11', 'dinner_announcement', 'group.dinner=', ?, 5)",
        (BOT,),
    )
    conn.execute(
        "INSERT INTO reactions VALUES (?, 5, ?, '🍳', '2026-10-08T08:00:00+00:00')", (BOT, ANNA)
    )
    conn.commit()
    conn.close()
    with Store(path) as store:
        announcement = store.tracked_message(WEEK, MessageKind.DINNER_ANNOUNCEMENT)
        assert announcement is not None
        assert (announcement.emoji, announcement.cook_emoji) == (None, None)
        assert count_guests(store, announcement, CONFIG) == Guests(count=1, cooks=1)
