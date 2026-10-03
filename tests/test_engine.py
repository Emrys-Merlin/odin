import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from odib.config import Config, parse_config
from odib.engine import Account, Step, dinner_week, reconcile
from odib.reactions import handle_reaction
from odib.signal import FakeSignalClient, ReactionEvent
from odib.store import Action, MessageKind, Outcome, Store

TEMPLATES = {
    "flat_ask": "ASK {emoji} bis {deadline}",
    "nudge": "NUDGE {deadline}",
    "cancellation": "ABGESAGT\n\nCANCELLED",
    "announcement": "ESSEN {dinner_time}\n\nDINNER {dinner_time}",
    "tally": "TALLY {count} x {emoji}",
    "hello": "HELLO",
    "flat_test": "TEST",
}


def make_config(**overrides: Any) -> Config:
    return parse_config({"templates": TEMPLATES, **overrides})


CONFIG = make_config()
BERLIN = CONFIG.timezone

ACCOUNT = Account(number="+490000000000", flat_group_id="group.flat=", dinner_group_id="group.d=")
FLAT, DINNER = ACCOUNT.flat_group_id, ACCOUNT.dinner_group_id
ANNA, BEN, CARL = "+4915100000001", "+4915100000002", "+4915100000003"

# A plain week (no DST change): dinner on Sunday 2026-10-11.
WEEK = date(2026, 10, 11)


def local(day: int, hour: int, minute: int = 0, month: int = 10, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=BERLIN)


def ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


@dataclass(frozen=True)
class Sent:
    at: datetime  # local time of the tick that sent it
    group: str
    text: str


class FlakyClient(FakeSignalClient):
    """A fake client whose next `failures` sends raise."""

    def __init__(self, first_timestamp: int) -> None:
        super().__init__(number=ACCOUNT.number, first_timestamp=first_timestamp)
        self.failures = 0

    async def send_group_message(self, group_id: str, text: str) -> int:
        if self.failures:
            self.failures -= 1
            raise ConnectionError("signal-cli-rest-api unreachable")
        return await super().send_group_message(group_id, text)


class Bot:
    """One running instance of the engine: a client, a store, and ticks at chosen times."""

    def __init__(self, store: Store, config: Config = CONFIG, first_timestamp: int = 1_000) -> None:
        self.store = store
        self.config = config
        self.client = FlakyClient(first_timestamp)
        self.log: list[Sent] = []
        self.steps: list[Step] = []
        self.now: datetime | None = None

    def tick(self, now: datetime) -> list[Step]:
        self.now = now
        before = len(self.client.sent)
        steps = asyncio.run(reconcile(self.config, self.store, self.client, ACCOUNT, now))
        for message in self.client.sent[before:]:
            self.log.append(Sent(now.astimezone(BERLIN), message.group_id, message.text))
        self.steps += steps
        return steps

    def run(self, start: datetime, end: datetime, every: timedelta = timedelta(minutes=15)) -> None:
        """Tick at `start`, `start + every`, … up to and excluding `end`."""
        now = start
        while now < end:
            self.tick(now)
            now += every

    def react(
        self,
        kind: MessageKind,
        reactor: str,
        *,
        at: datetime,
        week: date = WEEK,
        emoji: str = "👍",
        remove: bool = False,
    ) -> None:
        message = self.store.tracked_message(week, kind)
        assert message is not None, f"{kind} not sent"
        event = ReactionEvent(
            emoji=emoji,
            reactor=reactor,
            target_author=message.author,
            target_timestamp=message.timestamp,
            group_id=message.group_id,
            is_remove=remove,
            timestamp=ms(at),
        )
        handle_reaction(event, self.store, self.config, at)

    def texts(self) -> list[str]:
        return [sent.text.split("\n")[0] for sent in self.log]

    def outcomes(self, week: date = WEEK) -> dict[Action, Outcome]:
        found = {action: self.store.action_outcome(week, action) for action in Action}
        return {action: outcome for action, outcome in found.items() if outcome is not None}


@pytest.fixture
def store() -> Iterator[Store]:
    with Store(":memory:") as s:
        yield s


@pytest.fixture
def bot(store: Store) -> Bot:
    return Bot(store)


# --- Dinner week --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "week"),
    [
        (local(5, 9), WEEK),  # Monday
        (local(6, 18), WEEK),  # flat ask
        (local(11, 17, 59), WEEK),  # Sunday, just before dinner
        (local(11, 18), WEEK + timedelta(weeks=1)),  # dinner starts: next week
        (local(11, 23, 59), WEEK + timedelta(weeks=1)),
        (local(12, 0, 30), WEEK + timedelta(weeks=1)),
        (datetime(2026, 10, 11, 15, 59, tzinfo=UTC), WEEK),  # 17:59 CEST
        (datetime(2026, 10, 11, 16, 0, tzinfo=UTC), WEEK + timedelta(weeks=1)),
    ],
)
def test_dinner_week(now: datetime, week: date) -> None:
    assert dinner_week(CONFIG, now) == week


def test_dinner_week_across_dst() -> None:
    # Clocks go back on Sunday 2026-10-25 at 03:00; dinner is still at 18:00 local (17:00 UTC).
    sunday = date(2026, 10, 25)
    assert dinner_week(CONFIG, datetime(2026, 10, 25, 16, 59, tzinfo=UTC)) == sunday
    assert dinner_week(CONFIG, datetime(2026, 10, 25, 17, 0, tzinfo=UTC)) == sunday + timedelta(
        weeks=1
    )


def test_naive_now_is_rejected(bot: Bot) -> None:
    with pytest.raises(ValueError, match="naive"):
        bot.tick(datetime(2026, 10, 6, 18, 0))


# --- Full weeks ---------------------------------------------------------------------------------


def test_week_without_confirmation_is_cancelled(bot: Bot) -> None:
    bot.run(local(5, 0), local(12, 23))

    assert bot.log == [
        Sent(local(6, 18), FLAT, "ASK 👍 bis 18:00"),
        Sent(local(7, 12), FLAT, "NUDGE 18:00"),
        Sent(local(7, 18), DINNER, "ABGESAGT\n\nCANCELLED"),
    ]
    assert bot.outcomes() == {
        Action.FLAT_ASK: Outcome.SENT,
        Action.NUDGE: Outcome.SENT,
        Action.CANCELLATION: Outcome.SENT,
        Action.TALLY: Outcome.SKIPPED,
    }
    poll = bot.store.tracked_message(WEEK, MessageKind.FLAT_POLL)
    assert poll is not None and (poll.group_id, poll.author) == (FLAT, ACCOUNT.number)
    assert bot.store.tracked_message(WEEK, MessageKind.DINNER_ANNOUNCEMENT) is None


def test_week_with_confirmation_is_on(bot: Bot) -> None:
    bot.run(local(5, 0), local(6, 19))
    bot.react(MessageKind.FLAT_POLL, ANNA, at=local(6, 19))
    bot.run(local(6, 19), local(8, 9))
    bot.react(MessageKind.DINNER_ANNOUNCEMENT, BEN, at=local(8, 9))
    bot.react(MessageKind.DINNER_ANNOUNCEMENT, CARL, at=local(8, 10))
    bot.react(MessageKind.DINNER_ANNOUNCEMENT, ANNA, emoji="❤️", at=local(8, 11))
    bot.run(local(8, 9), local(12, 23))

    assert bot.log == [
        Sent(local(6, 18), FLAT, "ASK 👍 bis 18:00"),
        Sent(local(7, 18), DINNER, "ESSEN 18:00\n\nDINNER 18:00"),
        Sent(local(9, 14), FLAT, "TALLY 2 x 👍"),
    ]
    assert bot.outcomes() == {
        Action.FLAT_ASK: Outcome.SENT,
        Action.NUDGE: Outcome.SKIPPED,  # not needed: Anna confirmed
        Action.ANNOUNCEMENT: Outcome.SENT,
        Action.TALLY: Outcome.SENT,
    }
    announcement = bot.store.tracked_message(WEEK, MessageKind.DINNER_ANNOUNCEMENT)
    assert announcement is not None and announcement.group_id == DINNER


def test_withdrawn_confirmation_cancels(bot: Bot) -> None:
    bot.run(local(5, 0), local(6, 19))
    bot.react(MessageKind.FLAT_POLL, ANNA, at=local(6, 19))
    bot.run(local(6, 19), local(7, 13))
    bot.react(MessageKind.FLAT_POLL, ANNA, at=local(7, 13), remove=True)
    bot.run(local(7, 13), local(8, 0))
    # The nudge was not needed at 12:00; withdrawing later does not bring it back.
    assert bot.texts() == ["ASK 👍 bis 18:00", "ABGESAGT"]


def test_consecutive_weeks(bot: Bot) -> None:
    next_week = WEEK + timedelta(weeks=1)
    bot.run(local(5, 0), local(13, 19))
    bot.react(MessageKind.FLAT_POLL, ANNA, at=local(13, 19), week=next_week)
    bot.run(local(13, 19), local(19, 0))
    assert [(s.at, s.text.split("\n")[0]) for s in bot.log] == [
        (local(6, 18), "ASK 👍 bis 18:00"),
        (local(7, 12), "NUDGE 18:00"),
        (local(7, 18), "ABGESAGT"),
        (local(13, 18), "ASK 👍 bis 18:00"),
        (local(14, 18), "ESSEN 18:00"),
        (local(16, 14), "TALLY 0 x 👍"),
    ]


def test_tick_is_idempotent(bot: Bot) -> None:
    for _ in range(3):
        bot.tick(local(7, 18, 5))
    # A fresh install on Wednesday evening: the flat ask expired at the deadline, so the whole
    # week is skipped; ticking again changes nothing.
    assert bot.log == []
    assert bot.outcomes() == {
        Action.FLAT_ASK: Outcome.SKIPPED,
        Action.NUDGE: Outcome.SKIPPED,
        Action.CANCELLATION: Outcome.SKIPPED,
    }


def test_nudge_disabled(store: Store) -> None:
    bot = Bot(store, make_config(schedule={"nudge": {"enabled": False}}))
    bot.run(local(5, 0), local(12, 0))
    assert bot.texts() == ["ASK 👍 bis 18:00", "ABGESAGT"]
    assert Action.NUDGE not in bot.outcomes()


# --- Restarts and catch-up ----------------------------------------------------------------------


def test_restart_midweek_does_not_resend(tmp_path: Path) -> None:
    path = tmp_path / "odib.db"
    with Store(path) as store:
        first = Bot(store)
        first.run(local(5, 0), local(7, 13))
        assert first.texts() == ["ASK 👍 bis 18:00", "NUDGE 18:00"]
        first.react(MessageKind.FLAT_POLL, ANNA, at=local(7, 13))

    with Store(path) as store:
        second = Bot(store, first_timestamp=2_000)  # new engine and client, same database
        second.run(local(7, 13), local(12, 0))
        assert second.texts() == ["ESSEN 18:00", "TALLY 0 x 👍"]


def test_down_over_deadline_catches_up(bot: Bot) -> None:
    bot.run(local(5, 0), local(7, 17))
    # Anna confirms just before the deadline, but ODIN is down and only receives it on Thursday.
    bot.react(MessageKind.FLAT_POLL, ANNA, at=local(7, 17, 30))
    bot.tick(local(8, 10))
    assert bot.log[-1] == Sent(local(8, 10), DINNER, "ESSEN 18:00\n\nDINNER 18:00")
    bot.run(local(8, 10, 15), local(12, 0))
    assert bot.texts() == ["ASK 👍 bis 18:00", "NUDGE 18:00", "ESSEN 18:00", "TALLY 0 x 👍"]


def test_down_from_monday_until_sunday_catches_up_in_order(bot: Bot) -> None:
    bot.run(local(5, 0), local(6, 19))
    bot.react(MessageKind.FLAT_POLL, ANNA, at=local(6, 19))
    bot.tick(local(11, 17))  # back an hour before dinner: decision and tally both still due
    assert [s.at for s in bot.log] == [local(6, 18), local(11, 17), local(11, 17)]
    assert bot.texts() == ["ASK 👍 bis 18:00", "ESSEN 18:00", "TALLY 0 x 👍"]


def test_back_after_dinner_start_skips(bot: Bot) -> None:
    bot.run(local(5, 0), local(7, 17))
    bot.tick(local(11, 18, 30))
    assert bot.texts() == ["ASK 👍 bis 18:00", "NUDGE 18:00"]
    assert bot.outcomes() == {
        Action.FLAT_ASK: Outcome.SENT,
        Action.NUDGE: Outcome.SENT,
        Action.CANCELLATION: Outcome.SKIPPED,
        Action.TALLY: Outcome.SKIPPED,
    }
    # The next week runs normally.
    bot.run(local(11, 18, 45), local(14, 19))
    assert bot.texts()[2:] == ["ASK 👍 bis 18:00", "NUDGE 18:00", "ABGESAGT"]


def test_flat_ask_expires_at_the_deadline(bot: Bot) -> None:
    # Down from before the flat ask until after the deadline: asking now would be pointless,
    # since confirmations after the deadline do not count. The week is skipped entirely.
    bot.tick(local(5, 12))
    bot.run(local(7, 18), local(12, 0))
    assert bot.log == []
    assert bot.outcomes() == {
        Action.FLAT_ASK: Outcome.SKIPPED,
        Action.NUDGE: Outcome.SKIPPED,
        Action.CANCELLATION: Outcome.SKIPPED,
        Action.TALLY: Outcome.SKIPPED,
    }


def test_late_flat_ask_before_deadline_is_sent(bot: Bot) -> None:
    bot.tick(local(5, 12))
    bot.run(local(7, 9), local(8, 0))
    assert [(s.at, s.text.split("\n")[0]) for s in bot.log] == [
        (local(7, 9), "ASK 👍 bis 18:00"),
        (local(7, 12), "NUDGE 18:00"),
        (local(7, 18), "ABGESAGT"),
    ]


def test_grace_in_minutes(store: Store) -> None:
    bot = Bot(store, make_config(catch_up_grace=60))
    bot.run(local(5, 0), local(6, 19))
    bot.react(MessageKind.FLAT_POLL, ANNA, at=local(6, 19))
    bot.tick(local(7, 18, 59))  # within an hour of the deadline: still announced
    bot.tick(local(9, 15))  # more than an hour after the tally time: skipped
    assert bot.texts() == ["ASK 👍 bis 18:00", "ESSEN 18:00"]
    assert bot.outcomes()[Action.TALLY] is Outcome.SKIPPED


def test_grace_in_minutes_skips_late_flat_ask_and_week(store: Store) -> None:
    bot = Bot(store, make_config(catch_up_grace=60))
    bot.tick(local(5, 12))
    bot.run(local(6, 19, 15), local(12, 0))
    assert bot.log == []
    assert bot.outcomes()[Action.CANCELLATION] is Outcome.SKIPPED


def test_failed_send_is_retried_next_tick(bot: Bot) -> None:
    bot.tick(local(6, 17, 45))
    bot.client.failures = 1
    assert bot.tick(local(6, 18)) == []
    assert bot.outcomes() == {}
    assert bot.tick(local(6, 18, 15)) == [Step(WEEK, Action.FLAT_ASK, Outcome.SENT)]
    assert bot.texts() == ["ASK 👍 bis 18:00"]


def test_failed_send_blocks_later_steps(bot: Bot) -> None:
    bot.run(local(5, 0), local(7, 0))
    bot.client.failures = 1
    bot.tick(local(9, 15))  # nudge expired; the cancellation fails, so no tally decision yet
    assert bot.outcomes() == {Action.FLAT_ASK: Outcome.SENT, Action.NUDGE: Outcome.SKIPPED}
    bot.tick(local(9, 15, 15))
    assert bot.texts() == ["ASK 👍 bis 18:00", "ABGESAGT"]
    assert bot.outcomes()[Action.TALLY] is Outcome.SKIPPED


# --- DST ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sunday", "before", "after"),
    [
        # Clocks go back on Sunday 2026-10-25, 03:00 CEST → 02:00 CET.
        (date(2026, 10, 25), 2, 1),
        # Clocks go forward on Sunday 2027-03-28, 02:00 CET → 03:00 CEST.
        (date(2027, 3, 28), 1, 2),
    ],
)
def test_dst_week_keeps_local_times(store: Store, sunday: date, before: int, after: int) -> None:
    # Tally on Sunday morning, so the clock change falls between the announcement and the tally.
    bot = Bot(store, make_config(schedule={"tally": {"weekday": "sun", "time": "12:00"}}))
    tuesday, wednesday = sunday - timedelta(days=5), sunday - timedelta(days=4)
    # Tick in UTC, so the ticks themselves are unaffected by the change.
    start = datetime.combine(sunday - timedelta(days=7), datetime.min.time(), tzinfo=UTC)
    react_at = datetime.combine(tuesday, datetime.min.time(), tzinfo=UTC) + timedelta(hours=20)
    bot.run(start, react_at)
    bot.react(MessageKind.FLAT_POLL, ANNA, at=react_at, week=sunday)
    bot.run(react_at, start + timedelta(days=10, hours=13))

    assert [(s.at.date(), s.at.hour, s.at.minute, s.text.split("\n")[0]) for s in bot.log] == [
        (tuesday, 18, 0, "ASK 👍 bis 18:00"),
        (wednesday, 18, 0, "ESSEN 18:00"),
        (sunday, 12, 0, "TALLY 0 x 👍"),
        (tuesday + timedelta(weeks=1), 18, 0, "ASK 👍 bis 18:00"),
        (wednesday + timedelta(weeks=1), 12, 0, "NUDGE 18:00"),
    ]
    offsets = [s.at.utcoffset() for s in bot.log]
    assert offsets == [timedelta(hours=h) for h in (before, before, after, after, after)]
