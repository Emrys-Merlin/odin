import asyncio
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from odin.clock import FixedClock
from odin.config import Config, parse_config
from odin.reactions import consume_reactions, count_confirmations, same_emoji
from odin.signal import FakeSignalClient, ReactionEvent
from odin.store import MessageKind, Store, TrackedMessage

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
ANNA, BEN, CARL = "+4915100000001", "+4915100000002", "+4915100000003"

WEEK = date(2026, 10, 11)
FLAT_ASK = datetime(2026, 10, 6, 18, 0, tzinfo=BERLIN)
DEADLINE = datetime(2026, 10, 7, 18, 0, tzinfo=BERLIN)
TALLY = datetime(2026, 10, 9, 14, 0, tzinfo=BERLIN)


def ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


class World:
    """Fake client + store + fixed clock, with one flat poll and one announcement tracked."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.client = FakeSignalClient(number=BOT)
        self.clock = FixedClock(FLAT_ASK)
        self.poll = store.track_message(WEEK, MessageKind.FLAT_POLL, FLAT, BOT, ms(FLAT_ASK))
        self.announcement = store.track_message(
            WEEK, MessageKind.DINNER_ANNOUNCEMENT, DINNER, BOT, ms(DEADLINE)
        )

    def react(
        self,
        message: TrackedMessage,
        reactor: str,
        emoji: str = "👍",
        *,
        at: datetime,
        remove: bool = False,
        received: datetime | None = None,
        group_id: str | None = None,
    ) -> None:
        """Deliver one reaction, sent at ``at`` and received at ``received`` (default: ``at``)."""
        self.clock.set(received or at)
        self.client.inject(
            ReactionEvent(
                emoji=emoji,
                reactor=reactor,
                target_author=message.author,
                target_timestamp=message.timestamp,
                group_id=group_id or message.group_id,
                is_remove=remove,
                timestamp=ms(at),
            )
        )
        self._drain()

    def _drain(self) -> None:
        # Run the consumer over exactly the injected events: closing ends the stream.
        self.client.close()
        asyncio.run(consume_reactions(self.client, self.store, CONFIG, self.clock))

    def count(self, message: TrackedMessage) -> int:
        return count_confirmations(self.store, message, CONFIG.emoji)


@pytest.fixture
def world() -> Iterator[World]:
    with Store(":memory:") as store:
        yield World(store)


def after_ask(**delta: Any) -> datetime:
    return FLAT_ASK + timedelta(**delta)


def test_thumbs_up_counts(world: World) -> None:
    world.react(world.poll, ANNA, at=after_ask(minutes=5))
    world.react(world.poll, BEN, at=after_ask(hours=2))
    assert world.count(world.poll) == 2


def test_other_emoji_does_not_count(world: World) -> None:
    world.react(world.poll, ANNA, "❤️", at=after_ask(minutes=5))
    world.react(world.poll, BEN, "👍", at=after_ask(minutes=6))
    assert world.count(world.poll) == 1
    assert [r.emoji for r in world.store.reactions_for(world.poll)] == ["❤️", "👍"]


def test_skin_tone_variants_count(world: World) -> None:
    world.react(world.poll, ANNA, "👍🏽", at=after_ask(minutes=5))
    world.react(world.poll, BEN, "👍🏻", at=after_ask(minutes=6))
    assert world.count(world.poll) == 2


def test_same_emoji_ignores_modifiers_only() -> None:
    assert same_emoji("👍🏿", "👍")
    assert same_emoji("❤️", "❤")
    assert not same_emoji("👎", "👍")


def test_remove_withdraws(world: World) -> None:
    world.react(world.poll, ANNA, at=after_ask(minutes=5))
    world.react(world.poll, ANNA, at=after_ask(minutes=6), remove=True)
    assert world.count(world.poll) == 0
    assert world.store.reactions_for(world.poll) == []


def test_switching_to_another_emoji_withdraws(world: World) -> None:
    world.react(world.poll, ANNA, "👍", at=after_ask(minutes=5))
    world.react(world.poll, ANNA, "❤️", at=after_ask(minutes=6))
    assert world.count(world.poll) == 0


def test_stale_removal_keeps_the_current_reaction(world: World) -> None:
    # Switching 👍 → ❤️ → 👍 may also produce a removal of the old ❤️; it must not drop the 👍.
    world.react(world.poll, ANNA, "❤️", at=after_ask(minutes=5))
    world.react(world.poll, ANNA, "👍", at=after_ask(minutes=6))
    world.react(world.poll, ANNA, "❤️", at=after_ask(minutes=7), remove=True)
    assert world.count(world.poll) == 1


def test_reaction_after_deadline_ignored(world: World) -> None:
    world.react(world.poll, ANNA, at=DEADLINE)
    world.react(world.poll, BEN, at=DEADLINE + timedelta(minutes=1))
    assert world.count(world.poll) == 0


def test_removal_after_deadline_ignored(world: World) -> None:
    world.react(world.poll, ANNA, at=DEADLINE - timedelta(minutes=1))
    world.react(world.poll, ANNA, at=DEADLINE + timedelta(minutes=1), remove=True)
    world.react(world.poll, ANNA, "❤️", at=DEADLINE + timedelta(minutes=2))
    assert world.count(world.poll) == 1


def test_reaction_sent_before_deadline_but_received_late_counts(world: World) -> None:
    # ODIN was down over the deadline; the reaction is delivered when it comes back.
    sent = DEADLINE - timedelta(minutes=1)
    world.react(world.poll, ANNA, at=sent, received=DEADLINE + timedelta(hours=3))
    assert world.count(world.poll) == 1
    (reaction,) = world.store.reactions_for(world.poll)
    assert reaction.received_at == DEADLINE + timedelta(hours=3)


def test_announcement_has_no_deadline(world: World) -> None:
    world.react(world.announcement, ANNA, at=DEADLINE + timedelta(minutes=1))
    world.react(world.announcement, BEN, at=TALLY + timedelta(hours=5))
    world.react(world.announcement, CARL, "😢", at=TALLY + timedelta(hours=6))
    assert world.count(world.announcement) == 2


def test_announcement_removal_withdraws(world: World) -> None:
    world.react(world.announcement, ANNA, at=DEADLINE + timedelta(minutes=1))
    world.react(world.announcement, ANNA, at=TALLY + timedelta(days=1), remove=True)
    assert world.count(world.announcement) == 0


def test_polls_are_counted_separately(world: World) -> None:
    world.react(world.poll, ANNA, at=after_ask(minutes=5))
    world.react(world.announcement, BEN, at=DEADLINE + timedelta(minutes=1))
    world.react(world.announcement, CARL, at=DEADLINE + timedelta(minutes=2))
    assert world.count(world.poll) == 1
    assert world.count(world.announcement) == 2


def test_reaction_on_untracked_message_ignored(world: World) -> None:
    untracked = TrackedMessage(WEEK, MessageKind.FLAT_POLL, FLAT, BOT, ms(FLAT_ASK) + 1)
    world.react(untracked, ANNA, at=after_ask(minutes=5))
    other_author = TrackedMessage(WEEK, MessageKind.FLAT_POLL, FLAT, ANNA, ms(FLAT_ASK))
    world.react(other_author, BEN, at=after_ask(minutes=5))
    assert world.count(world.poll) == 0
    assert world.store.reactions_for(world.poll) == []


def test_reaction_from_another_group_ignored(world: World) -> None:
    world.react(world.poll, ANNA, at=after_ask(minutes=5), group_id=DINNER)
    assert world.count(world.poll) == 0
