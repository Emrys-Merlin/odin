"""Changing the dinner weekday from chat (#77): never inside the running dinner week.

A week dropped by the switch gets the cancellation in the dinner group, exactly once (#80).
"""

import asyncio
import logging
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest

from odin.commands import CommandContext, handle
from odin.commands.settime import RESET, SAVED
from odin.config import Config, ConfigError, WeeklyTime, parse_config
from odin.engine import (
    Account,
    Transition,
    dinner_week,
    reconcile,
    record_transition,
    step_windows,
    transition,
)
from odin.overrides import (
    DINNER_KEY,
    PENDING_DINNER_KEY,
    apply_overrides,
    effective_config,
    format_weekly_time,
    pending_dinner,
)
from odin.reactions import handle_reaction
from odin.signal import FakeSignalClient, ReactionEvent
from odin.store import _MIGRATIONS, Action, AppliedDinner, MessageKind, Outcome, Store

TEMPLATES = {
    "flat_ask": "ASK {dinner_day_de}",
    "nudge": "NUDGE",
    "cancellation": "ABGESAGT {dinner_day_de}\n\nCANCELLED {dinner_day_en}",
    "announcement": "ESSEN {dinner_day_de}\n\nDINNER {dinner_day_en}",
    "tally": "TALLY {count}",
    "hello": "HELLO",
    "flat_test": "TEST",
}


def make_config(**data: Any) -> Config:
    return parse_config({"templates": TEMPLATES, **data})


# Default schedule (flat ask Tue 18:00, nudge Wed 12:00, deadline Wed 18:00, tally Fri 14:00,
# cook Sun 17:00, dinner Sun 18:00). Sun → Mon fits it as it is.
CONFIG = make_config()
# For Sun → Sat, cooking has to move off Sunday first.
SAT_COOK = make_config(schedule={"cook": {"weekday": "sat", "time": "17:00"}})
BERLIN = CONFIG.timezone
ACCOUNT = Account(number="+490000000000", flat_group_id="group.flat=", dinner_group_id="group.d=")
ANNA, BEN = "+4915100000001", "+4915100000002"


def local(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=BERLIN)


def oct(day: int, hour: int, minute: int = 0) -> datetime:
    return local(10, day, hour, minute)


# October 2026: Sun 11., Tue 13., Thu 15., Sat 17., Sun 18., Mon 19., Sat 24., Sun 25., Mon 26.
SUN_18, MON_19, SAT_24, SUN_25, MON_26 = (date(2026, 10, d) for d in (18, 19, 24, 25, 26))


@pytest.fixture
def store() -> Iterator[Store]:
    with Store(":memory:") as store:
        yield store


def send(store: Store, text: str, now: datetime, base: Config = CONFIG) -> str:
    ctx = CommandContext(
        base=base,
        config=effective_config(base, store, now),
        store=store,
        now=now,
        sender=ANNA,
        sender_name="Anna",
    )
    return handle(text, ctx)[0]  # /settext adds a preview as a second reply


def stored(store: Store) -> dict[str, tuple[str, date | None]]:
    return {key: (o.value, o.after_week) for key, o in store.overrides().items()}


# --- When the change applies --------------------------------------------------------------------


@pytest.mark.parametrize("now", [oct(13, 19), oct(15, 12), oct(17, 20), oct(18, 17, 59)])
def test_change_during_a_started_week_waits_for_its_dinner(store: Store, now: datetime) -> None:
    reply = send(store, "/settime dinner sat 18:00", now, SAT_COOK)
    assert reply == "\n".join(
        [
            SAVED,
            "Essen (dinner): So 18:00 → Sa 18:00",
            "Das gilt ab dem Essen am Sa 24.10. um 18:00. "
            "Diese Woche bleibt es beim Essen am So 18.10. um 18:00.",
        ]
    )
    assert stored(store) == {PENDING_DINNER_KEY: ("sat 18:00", SUN_18)}

    # The running week is untouched until its dinner starts …
    before = effective_config(SAT_COOK, store, oct(18, 17, 59))
    assert before == SAT_COOK
    assert dinner_week(before, oct(18, 17, 59)) == SUN_18
    # … and from then on the new weekday applies, stored as a plain override.
    after = effective_config(SAT_COOK, store, oct(18, 18))
    assert after.schedule.dinner == WeeklyTime(5, time(18, 0))
    assert dinner_week(after, oct(18, 18)) == SAT_24
    assert stored(store) == {DINNER_KEY: ("sat 18:00", None)}


def test_change_on_tuesday_before_the_flat_ask_applies_this_week(store: Store) -> None:
    # Nothing of the week of Sun 18. has happened yet, so it is simply replaced.
    reply = send(store, "/settime dinner sat 18:00", oct(13, 10), SAT_COOK)
    assert reply.splitlines()[1:] == [
        "Essen (dinner): So 18:00 → Sa 18:00",
        "Das gilt schon ab dieser Woche: nächstes Essen am Sa 17.10. um 18:00.",
    ]
    assert stored(store) == {DINNER_KEY: ("sat 18:00", None)}
    assert dinner_week(effective_config(SAT_COOK, store, oct(13, 10)), oct(13, 10)) == date(
        2026, 10, 17
    )


def test_change_after_dinner_applies_at_once_from_the_new_week(store: Store) -> None:
    reply = send(store, "/settime dinner sat 18:00", oct(11, 19), SAT_COOK)
    assert reply.splitlines()[2] == (
        "Das gilt schon ab dieser Woche: nächstes Essen am Sa 17.10. um 18:00."
    )
    assert stored(store) == {DINNER_KEY: ("sat 18:00", None)}


def test_a_recorded_step_counts_as_started(store: Store) -> None:
    # The flat ask is not due yet, but something is recorded for the week (e.g. a catch-up).
    store.record_action(SUN_18, Action.FLAT_ASK, oct(13, 9))
    send(store, "/settime dinner sat 18:00", oct(13, 10), SAT_COOK)
    assert stored(store) == {PENDING_DINNER_KEY: ("sat 18:00", SUN_18)}


def test_sun_to_mon_drops_the_cut_short_week(store: Store) -> None:
    reply = send(store, "/settime dinner mon 18:00", oct(15, 12))
    assert reply == "\n".join(
        [
            SAVED,
            "Essen (dinner): So 18:00 → Mo 18:00",
            "Das gilt ab dem Essen am Mo 26.10. um 18:00. "
            "Diese Woche bleibt es beim Essen am So 18.10. um 18:00.",
            "Achtung: Am Mo 19.10. gibt es kein Essen – diese Woche fällt beim Wechsel aus, weil "
            "ihre Frage an die WG schon vor dem Wechsel dran gewesen wäre.",
            "Die Absage für den Mo 19.10. schicke ich der Essensgruppe beim Wechsel "
            "(So 18.10. um 18:00).",
        ]
    )
    # Nothing is recorded as dropped before the switch applies.
    assert store.dropped_at(MON_19) is None
    pending = pending_dinner(CONFIG, store, oct(15, 12))
    assert pending is not None
    assert (pending.transition.first_week, pending.transition.dropped_week) == (MON_26, MON_19)


def test_sun_to_mon_right_after_dinner_drops_tomorrows_week(store: Store) -> None:
    reply = send(store, "/settime dinner mon 18:00", oct(11, 19))
    assert reply.splitlines()[2:] == [
        "Das gilt schon ab dieser Woche: nächstes Essen am Mo 19.10. um 18:00.",
        "Achtung: Am Mo 12.10. gibt es kein Essen – diese Woche fällt beim Wechsel aus, weil "
        "ihre Frage an die WG schon vor dem Wechsel dran gewesen wäre.",
        "Die Absage für den Mo 12.10. schicke ich der Essensgruppe gleich.",
    ]
    # Applied at once: the dropped week is recorded with the command's time as the switch.
    assert store.dropped_at(date(2026, 10, 12)) == oct(11, 19).astimezone(UTC)


def test_order_is_checked_for_the_new_weekday(store: Store) -> None:
    # Cooking on Sunday 17:00 would lie before the deadline of a Saturday dinner.
    reply = send(store, "/settime dinner sat 18:00", oct(15, 12))
    assert reply.startswith("Das passt nicht: flat_deadline muss vor cook liegen.")
    assert stored(store) == {}


def test_hardcoded_weekday_warning(store: Store) -> None:
    send(store, "/settext nudge\nBis Mittwoch!", oct(12, 10), SAT_COOK)
    reply = send(store, "/settime dinner sat 18:00", oct(15, 12), SAT_COOK)
    assert reply.splitlines()[-1].startswith("Achtung: Die Vorlage nudge nennt einen Wochentag")


# --- Pending changes: /schedule, /resettime, later changes --------------------------------------


def test_schedule_shows_the_pending_change(store: Store) -> None:
    send(store, "/settime dinner sat 18:00", oct(15, 12), SAT_COOK)
    lines = send(store, "/schedule", oct(15, 13), SAT_COOK).splitlines()
    assert lines[6] == "dinner – Essen: So 18:00 → ab 24.10.: Sa 18:00 ✏️ 15.10. von Anna"
    assert lines[5] == "cook – Mitkochen: Sa 17:00"


def test_schedule_shows_a_dropped_week(store: Store) -> None:
    send(store, "/settime dinner mon 18:00", oct(15, 12))
    lines = send(store, "/schedule", oct(15, 13)).splitlines()
    assert lines[6] == (
        "dinner – Essen: So 18:00 → ab 26.10.: Mo 18:00 (Mo 19.10. entfällt) ✏️ 15.10. von Anna"
    )


def test_schedule_after_the_switch(store: Store) -> None:
    send(store, "/settime dinner sat 18:00", oct(15, 12), SAT_COOK)
    lines = send(store, "/schedule", oct(19, 10), SAT_COOK).splitlines()
    assert lines[6] == "dinner – Essen: Sa 18:00 ✏️ 15.10. von Anna"


def test_resettime_cancels_a_pending_change(store: Store) -> None:
    send(store, "/settime dinner sun 19:00", oct(15, 11), SAT_COOK)
    send(store, "/settime dinner sat 18:00", oct(15, 12), SAT_COOK)
    reply = send(store, "/resettime dinner", oct(16, 9), SAT_COOK)
    assert reply == "\n".join(
        [
            "Verworfen ✅ Der geplante Wechsel auf Sa 18:00 (ab Sa 24.10.) fällt weg.",
            "Essen (dinner): So 19:00, nächstes Mal So 18.10. um 19:00",
        ]
    )
    # Only the pending change is gone; this week's new time stays.
    assert stored(store) == {DINNER_KEY: ("sun 19:00", None)}
    assert effective_config(SAT_COOK, store, oct(20, 9)).schedule.dinner.weekday == 6


def test_a_new_time_on_the_current_weekday_discards_a_pending_change(store: Store) -> None:
    send(store, "/settime dinner sat 18:00", oct(15, 12), SAT_COOK)
    reply = send(store, "/settime dinner sun 19:00", oct(15, 13), SAT_COOK)
    assert reply.splitlines()[0] == SAVED
    assert reply.splitlines()[-1] == (
        "Der geplante Wechsel auf Sa 18:00 (ab Sa 24.10.) ist damit verworfen."
    )
    assert stored(store) == {DINNER_KEY: ("sun 19:00", None)}


def test_another_weekday_replaces_a_pending_change(store: Store) -> None:
    send(store, "/settime dinner sat 18:00", oct(15, 12), SAT_COOK)
    send(store, "/settime dinner mon 18:00", oct(15, 13), SAT_COOK)
    assert stored(store) == {PENDING_DINNER_KEY: ("mon 18:00", SUN_18)}


def test_later_changes_must_fit_the_pending_weekday_too(store: Store) -> None:
    send(store, "/settime dinner sat 18:00", oct(15, 12), SAT_COOK)
    # Fine for this Sunday, but not for the Saturdays to come.
    reply = send(store, "/settime cook sun 17:00", oct(15, 13), SAT_COOK)
    assert reply.startswith(
        "Mit dem neuen Essenstag (Sa 18:00, ab Sa 24.10.): "
        "Das passt nicht: flat_deadline muss vor cook liegen."
    )
    assert stored(store) == {PENDING_DINNER_KEY: ("sat 18:00", SUN_18)}
    # Something that fits both is accepted, and the pending change stays.
    assert send(store, "/settime cook sat 16:00", oct(15, 13), SAT_COOK).startswith(SAVED)
    assert PENDING_DINNER_KEY in stored(store)


def test_other_commands_ignore_the_pending_key(store: Store) -> None:
    send(store, "/settime dinner sat 18:00", oct(15, 12), SAT_COOK)
    assert send(store, "/nudge off", oct(15, 13), SAT_COOK).startswith(SAVED)
    assert send(store, "/settext nudge\nNoch keiner", oct(15, 13), SAT_COOK).startswith(
        "Gespeichert"
    )
    assert send(store, "/resettime nudge", oct(15, 13), SAT_COOK).startswith(RESET)


def test_resettime_back_to_the_config_weekday_waits_too(store: Store) -> None:
    send(store, "/settime dinner sat 18:00", oct(11, 19), SAT_COOK)  # at once
    assert stored(store) == {DINNER_KEY: ("sat 18:00", None)}
    reply = send(store, "/resettime dinner", oct(15, 12), SAT_COOK)  # Sat 17. week is running
    assert reply.splitlines()[:3] == [
        RESET,
        "Essen (dinner): Sa 18:00 → So 18:00",
        "Das gilt ab dem Essen am So 25.10. um 18:00. "
        "Diese Woche bleibt es beim Essen am Sa 17.10. um 18:00.",
    ]
    assert stored(store)[PENDING_DINNER_KEY] == ("sun 18:00", date(2026, 10, 17))
    # Once it applies, nothing is overridden any more.
    assert effective_config(SAT_COOK, store, oct(17, 18)) == SAT_COOK
    assert stored(store) == {}


def test_resettime_back_to_the_config_weekday_at_once(store: Store) -> None:
    send(store, "/settime dinner sat 18:00", oct(11, 19), SAT_COOK)
    send(store, "/resettime dinner", oct(12, 10), SAT_COOK)  # Sat 17. week has not started
    assert stored(store) == {}


# --- effective_config ---------------------------------------------------------------------------


def test_a_pending_change_wins_over_a_new_toml_weekday(store: Store) -> None:
    send(store, "/settime dinner sat 18:00", oct(15, 12), SAT_COOK)
    moved = make_config(
        schedule={
            "cook": {"weekday": "sat", "time": "17:00"},
            "dinner": {"weekday": "sat", "time": "19:00"},
        }
    )
    # The pending change waits for the week of Sun 18., so the TOML's new weekday waits too …
    assert effective_config(moved, store, oct(15, 13)) == SAT_COOK
    pending = pending_dinner(moved, store, oct(15, 13))
    assert pending is not None and not pending.from_config
    assert pending.point == WeeklyTime(5, time(18, 0))
    # … and at the switch the chat change takes over, hiding the TOML's dinner time.
    assert effective_config(moved, store, oct(18, 18)).schedule.dinner == WeeklyTime(5, time(18))
    assert stored(store) == {DINNER_KEY: ("sat 18:00", None)}
    assert store.applied_dinner() == AppliedDinner("sat 18:00")


def test_pending_change_is_dropped_when_it_no_longer_fits(store: Store) -> None:
    send(store, "/settime dinner sat 18:00", oct(15, 12), SAT_COOK)
    # The TOML moves cooking back to Sunday, which no Saturday dinner allows.
    assert effective_config(CONFIG, store, oct(15, 13)) == CONFIG
    assert stored(store) == {}


# --- The engine across the switch ---------------------------------------------------------------


@dataclass(frozen=True)
class Sent:
    at: datetime
    text: str


class Bot:
    """The running bot as `odin.app` drives it: each tick with the effective config of its time."""

    def __init__(self, store: Store, base: Config) -> None:
        self.store = store
        self.base = base
        self.client = FakeSignalClient(number=ACCOUNT.number)
        self.log: list[Sent] = []

    def tick(self, now: datetime) -> None:
        before = len(self.client.sent)
        config = effective_config(self.base, self.store, now)
        asyncio.run(reconcile(config, self.store, self.client, ACCOUNT, now))
        for message in self.client.sent[before:]:
            self.log.append(Sent(now.astimezone(BERLIN), message.text.split("\n")[0]))

    def react(self, now: datetime) -> None:
        """Ben confirms on this week's flat poll and announcement, if they are out."""
        config = effective_config(self.base, self.store, now)
        week = dinner_week(config, now)
        for kind in MessageKind:
            message = self.store.tracked_message(week, kind)
            if message is None or self.store.reactions_for(message):
                continue
            event = ReactionEvent(
                emoji="👍",
                reactor=BEN,
                target_author=message.author,
                target_timestamp=message.timestamp,
                group_id=message.group_id,
                is_remove=False,
                timestamp=int(now.timestamp() * 1000),
            )
            handle_reaction(event, self.store, config, now)

    def run(
        self,
        start: datetime,
        end: datetime,
        commands: dict[datetime, str] | None = None,
        every: timedelta = timedelta(minutes=30),
    ) -> None:
        commands = dict(commands or {})
        now = start
        while now < end:
            for at in [at for at in commands if at <= now]:
                send(self.store, commands.pop(at), at, self.base)
            self.tick(now)
            self.react(now)
            now += every
        assert not commands

    def sent(self) -> list[tuple[str, str]]:
        return [(f"{s.at:%a %d.%m. %H:%M}", s.text) for s in self.log]

    def outcomes(self, week: date) -> dict[Action, Outcome]:
        found = {action: self.store.action_outcome(week, action) for action in Action}
        return {action: outcome for action, outcome in found.items() if outcome is not None}


ALL_SENT = {
    Action.FLAT_ASK: Outcome.SENT,
    Action.NUDGE: Outcome.SKIPPED,  # Ben confirmed right away
    Action.ANNOUNCEMENT: Outcome.SENT,
    Action.TALLY: Outcome.SENT,
}
ALL_SKIPPED = {
    Action.FLAT_ASK: Outcome.SKIPPED,
    Action.NUDGE: Outcome.SKIPPED,
    Action.CANCELLATION: Outcome.SKIPPED,
    Action.TALLY: Outcome.SKIPPED,
}
# A dropped week: never asked, but the dinner group gets the cancellation.
DROPPED = ALL_SKIPPED | {Action.CANCELLATION: Outcome.SENT}


def test_sun_to_sat_across_the_switch_sends_everything_once(store: Store) -> None:
    bot = Bot(store, SAT_COOK)
    bot.run(oct(12, 9), local(11, 1, 9), {oct(15, 12): "/settime dinner sat 18:00"})
    assert bot.sent() == [
        ("Tue 13.10. 18:00", "ASK Sonntag"),
        ("Wed 14.10. 18:00", "ESSEN Sonntag"),
        ("Fri 16.10. 14:00", "TALLY 1"),
        ("Tue 20.10. 18:00", "ASK Samstag"),
        ("Wed 21.10. 18:00", "ESSEN Samstag"),
        ("Fri 23.10. 14:00", "TALLY 1"),
        ("Tue 27.10. 18:00", "ASK Samstag"),
        ("Wed 28.10. 18:00", "ESSEN Samstag"),
        ("Fri 30.10. 14:00", "TALLY 1"),
    ]
    for week in (SUN_18, SAT_24, date(2026, 10, 31)):
        assert bot.outcomes(week) == ALL_SENT
    # The Saturday "before" the switch never existed and is never touched.
    assert bot.outcomes(date(2026, 10, 17)) == {}
    assert bot.outcomes(SUN_25) == {}


def test_sun_to_mon_drops_one_week_and_never_asks_twice(store: Store) -> None:
    bot = Bot(store, CONFIG)
    bot.run(oct(12, 9), local(11, 3, 9), {oct(15, 12): "/settime dinner mon 18:00"})
    assert bot.sent() == [
        ("Tue 13.10. 18:00", "ASK Sonntag"),
        ("Wed 14.10. 18:00", "ESSEN Sonntag"),
        ("Fri 16.10. 14:00", "TALLY 1"),
        # Mon 19.: its flat ask would have been Tue 13. — dropped; only its cancellation goes
        # out, right when Sunday's dinner starts, naming the new weekday.
        ("Sun 18.10. 18:00", "ABGESAGT Montag"),
        ("Tue 20.10. 18:00", "ASK Montag"),
        ("Wed 21.10. 18:00", "ESSEN Montag"),
        ("Fri 23.10. 14:00", "TALLY 1"),
        ("Tue 27.10. 18:00", "ASK Montag"),
        ("Wed 28.10. 18:00", "ESSEN Montag"),
        ("Fri 30.10. 14:00", "TALLY 1"),
    ]
    assert bot.outcomes(SUN_18) == ALL_SENT
    assert bot.outcomes(MON_19) == DROPPED
    assert bot.outcomes(MON_26) == ALL_SENT
    assert bot.outcomes(date(2026, 10, 12)) == {}
    # The whole bilingual cancellation, to the dinner group.
    [cancellation] = [m for m in bot.client.sent if m.text.startswith("ABGESAGT")]
    assert cancellation.group_id == ACCOUNT.dinner_group_id
    assert cancellation.text == "ABGESAGT Montag\n\nCANCELLED Monday"


def test_sun_to_mon_right_after_dinner(store: Store) -> None:
    bot = Bot(store, CONFIG)
    bot.run(oct(5, 9), oct(27, 9), {oct(11, 19): "/settime dinner mon 18:00"})
    assert [text for _, text in bot.sent()] == [
        "ASK Sonntag",  # Tue 6.
        "ESSEN Sonntag",
        "TALLY 1",
        "ABGESAGT Montag",  # Sun 11. 19:00, right after the command: Mon 12. is dropped
        "ASK Montag",  # Tue 13., for Mon 19.
        "ESSEN Montag",
        "TALLY 1",
        "ASK Montag",  # Tue 20., for Mon 26.
        "ESSEN Montag",
        "TALLY 1",
    ]
    assert bot.sent()[3] == ("Sun 11.10. 19:00", "ABGESAGT Montag")
    assert bot.outcomes(date(2026, 10, 12)) == DROPPED
    assert bot.outcomes(MON_19) == ALL_SENT


def test_the_bot_down_over_the_switch_finishes_the_old_week(store: Store) -> None:
    bot = Bot(store, CONFIG)
    bot.run(oct(12, 9), oct(16, 12), {oct(15, 12): "/settime dinner mon 18:00"})
    assert bot.outcomes(SUN_18) == {
        Action.FLAT_ASK: Outcome.SENT,
        Action.NUDGE: Outcome.SKIPPED,
        Action.ANNOUNCEMENT: Outcome.SENT,
    }
    # Down from Fri 16. 12:00 until Mon 19. 10:00: the tally of Sun 18. was missed.
    bot.run(oct(19, 10), oct(19, 11))
    assert bot.outcomes(SUN_18)[Action.TALLY] is Outcome.SKIPPED
    # Back before Mon 19.'s dinner, within the grace: its cancellation is still posted, once.
    assert bot.outcomes(MON_19) == DROPPED
    assert [text for _, text in bot.sent()] == ["ASK Sonntag", "ESSEN Sonntag", "ABGESAGT Montag"]
    assert bot.outcomes(date(2026, 10, 12)) == {}


def test_back_after_the_dropped_weeks_dinner_posts_nothing(store: Store) -> None:
    bot = Bot(store, CONFIG)
    bot.run(oct(12, 9), oct(16, 12), {oct(15, 12): "/settime dinner mon 18:00"})
    # Down from Fri 16. 12:00 until Tue 20. 10:00, after Mon 19.'s dinner.
    bot.run(oct(20, 10), oct(20, 11))
    assert store.dropped_at(MON_19) == oct(18, 18).astimezone(UTC)
    assert bot.outcomes(MON_19) == ALL_SKIPPED
    # The old week, whose tally was missed, is finished too (#81): nothing stays open.
    assert bot.outcomes(SUN_18)[Action.TALLY] is Outcome.SKIPPED
    assert store.unfinished_weeks_before(MON_26) == []
    assert [text for _, text in bot.sent()] == ["ASK Sonntag", "ESSEN Sonntag"]
    # The Monday weeks go on normally.
    bot.run(oct(20, 11), oct(27, 9))
    assert bot.outcomes(MON_26) == ALL_SENT
    assert "ABGESAGT Montag" not in [text for _, text in bot.sent()]


@pytest.mark.parametrize(
    ("back", "posted"),
    [(oct(18, 18, 30), True), (oct(18, 19, 0), False), (oct(19, 10), False)],
)
def test_the_grace_counts_from_the_switch(store: Store, back: datetime, posted: bool) -> None:
    base = make_config(catch_up_grace=60)
    bot = Bot(store, base)
    bot.run(oct(12, 9), oct(18, 17), {oct(15, 12): "/settime dinner mon 18:00"})
    bot.run(back, back + timedelta(minutes=1))  # down from Sun 17:00 until `back`
    outcome = Outcome.SENT if posted else Outcome.SKIPPED
    assert bot.outcomes(MON_19) == ALL_SKIPPED | {Action.CANCELLATION: outcome}
    assert ("ABGESAGT Montag" in [text for _, text in bot.sent()]) is posted


def test_a_restart_over_the_switch_posts_the_cancellation_once(store: Store) -> None:
    bot = Bot(store, CONFIG)
    bot.run(oct(12, 9), oct(18, 18), {oct(15, 12): "/settime dinner mon 18:00"})
    # A command right at the switch applies it (and records the dropped week) before the next
    # tick does.
    send(store, "/schedule", oct(18, 18, 0))
    assert store.dropped_at(MON_19) == oct(18, 18).astimezone(UTC)
    assert PENDING_DINNER_KEY not in stored(store)
    # The bot restarts a few times around the switch: a new client each time, same DB.
    restarted = [Bot(store, CONFIG) for _ in range(3)]
    for restart, now in zip(restarted, (oct(18, 18, 1), oct(18, 18, 2), oct(18, 20)), strict=True):
        restart.tick(now)
    assert [s.text for r in restarted for s in r.log] == ["ABGESAGT Montag"]
    assert restarted[0].log[0].at == oct(18, 18, 1)
    bot = Bot(store, CONFIG)
    bot.run(oct(18, 20), oct(19, 20))
    assert bot.log == []
    assert bot.outcomes(MON_19) == DROPPED


class FlakyClient(FakeSignalClient):
    """Fails the first `failures` sends."""

    def __init__(self, failures: int) -> None:
        super().__init__(number=ACCOUNT.number)
        self.failures = failures

    async def send_group_message(self, group_id: str, text: str) -> int:
        if self.failures:
            self.failures -= 1
            raise ConnectionError("signal-cli is down")
        return await super().send_group_message(group_id, text)


def test_a_failed_cancellation_is_retried_and_sent_once(store: Store) -> None:
    bot = Bot(store, CONFIG)
    bot.run(oct(12, 9), oct(18, 18), {oct(15, 12): "/settime dinner mon 18:00"})
    flaky = FlakyClient(failures=2)
    for minute in range(5):
        now = oct(18, 18, minute)
        asyncio.run(reconcile(effective_config(CONFIG, store, now), store, flaky, ACCOUNT, now))
    assert [m.text.split("\n")[0] for m in flaky.sent] == ["ABGESAGT Montag"]
    assert store.action_time(MON_19, Action.CANCELLATION) == oct(18, 18, 2).astimezone(UTC)


def test_a_switch_that_drops_no_week_records_none(store: Store) -> None:
    bot = Bot(store, SAT_COOK)
    bot.run(oct(12, 9), oct(25, 9), {oct(15, 12): "/settime dinner sat 18:00"})
    assert [text for _, text in bot.sent() if text.startswith("ABGESAGT")] == []
    for week in (date(2026, 10, 17), SUN_18, SAT_24):
        assert store.dropped_at(week) is None


def test_record_transition(store: Store) -> None:
    switch = oct(18, 18)
    monday = apply_overrides(CONFIG, {DINNER_KEY: "mon 18:00"})
    record_transition(store, transition(monday, switch))
    assert store.dropped_at(MON_19) == switch.astimezone(UTC)
    assert store.dropped_at(MON_26) is None
    # A later switch that runs Mon 19. normally (a made-up one here) undoes it.
    record_transition(store, Transition(switch, MON_19, None))
    assert store.dropped_at(MON_19) is None


def test_late_reaction_on_the_old_poll_is_ignored(store: Store) -> None:
    bot = Bot(store, CONFIG)
    bot.run(oct(12, 9), oct(14, 12), {oct(13, 19): "/settime dinner mon 18:00"})
    poll = store.tracked_message(SUN_18, MessageKind.FLAT_POLL)
    assert poll is not None
    event = ReactionEvent(
        emoji="👍",
        reactor=ANNA,
        target_author=poll.author,
        target_timestamp=poll.timestamp,
        group_id=poll.group_id,
        is_remove=False,
        timestamp=int(oct(14, 11).timestamp() * 1000),  # sent in time, delivered late
    )
    later = oct(20, 9)
    assert not handle_reaction(event, store, effective_config(CONFIG, store, later), later)


# --- transition ---------------------------------------------------------------------------------

# Every 3 hours of the week, as new dinner times.
_GRID = [WeeklyTime(day, time(hour, 0)) for day in range(7) for hour in range(0, 24, 3)]
_LAYOUTS = [
    {},
    {"cook": {"weekday": "wed", "time": "20:00"}},
    {
        "flat_ask": {"weekday": "sat", "time": "10:00"},
        "nudge": {"weekday": "sat", "time": "20:00"},
        "flat_deadline": {"weekday": "sun", "time": "10:00"},
        "rsvp_by": {"weekday": "sun", "time": "12:00"},
        "tally": {"weekday": "sun", "time": "12:00"},
        "cook": {"weekday": "sun", "time": "14:00"},
        "dinner": {"weekday": "mon", "time": "19:00"},
    },
    {"nudge": {"enabled": False}, "cook": {"weekday": "thu", "time": "18:00"}},
]


@pytest.mark.parametrize("layout", range(len(_LAYOUTS)))
def test_no_week_is_ever_cut_in_half(layout: int) -> None:
    """For every new dinner time that fits the schedule, switching at an old dinner (or at a
    moment before the next flat ask) never starts a week whose steps lie on both sides."""
    old = make_config(schedule=_LAYOUTS[layout])
    old_week = dinner_week(old, oct(12, 0))
    old_dinner = old.when(old.schedule.dinner, old_week)
    previous_dinner = old.when(old.schedule.dinner, old_week - timedelta(weeks=1))
    flat_ask = old.when(old.schedule.flat_ask, old_week)
    checked = 0
    for point in _GRID:
        try:
            new = apply_overrides(old, {DINNER_KEY: format_weekly_time(point)})
        except ConfigError:
            continue
        checked += 1
        transition(new, old_dinner)  # raises if a week would be cut in half
        hours = int((flat_ask - previous_dinner).total_seconds() // 3600)
        for hour in range(0, hours, 5):
            moment = previous_dinner + timedelta(hours=hour)
            weeks = transition(new, moment)
            for window in step_windows(new, weeks.first_week):
                assert window.start > moment.astimezone(UTC)
    assert checked > 10


def test_a_switch_inside_a_week_is_refused() -> None:
    with pytest.raises(ValueError, match="would start before"):
        transition(CONFIG, oct(13, 19))  # between the flat ask and the deadline of Sun 18.


# --- Store --------------------------------------------------------------------------------------


def test_upgrade_from_version_4_keeps_overrides(tmp_path: Path) -> None:
    path = tmp_path / "odin.db"
    conn = sqlite3.connect(path)
    conn.executescript(f"{'; '.join(_MIGRATIONS[:4])}; PRAGMA user_version = 4;")
    conn.execute(
        "INSERT INTO overrides VALUES ('schedule.tally', 'sat 10:00', 'Tim', ?)",
        (oct(12, 10).astimezone(UTC).isoformat(),),
    )
    conn.commit()
    conn.close()
    with Store(path) as store:
        [override] = store.overrides().values()
        assert (override.key, override.value, override.after_week) == (
            "schedule.tally",
            "sat 10:00",
            None,
        )
        store.set_override(PENDING_DINNER_KEY, "sat 18:00", "Tim", oct(12, 11), SUN_18)
        assert store.overrides()[PENDING_DINNER_KEY].after_week == SUN_18
        # Setting it again without a week clears it.
        store.set_override(PENDING_DINNER_KEY, "sat 18:00", "Tim", oct(12, 12))
        assert store.overrides()[PENDING_DINNER_KEY].after_week is None


def test_upgrade_from_version_5_adds_dropped_weeks(tmp_path: Path) -> None:
    path = tmp_path / "odin.db"
    conn = sqlite3.connect(path)
    conn.executescript(f"{'; '.join(_MIGRATIONS[:5])}; PRAGMA user_version = 5;")
    conn.close()
    with Store(path) as store:
        assert store.dropped_at(MON_19) is None
        assert store.record_dropped_week(MON_19, oct(18, 18))
        # The first record wins.
        assert not store.record_dropped_week(MON_19, oct(18, 19))
        assert store.dropped_at(MON_19) == oct(18, 18).astimezone(UTC)
        assert store.delete_dropped_week(MON_19)
        assert not store.delete_dropped_week(MON_19)
        assert store.dropped_at(MON_19) is None


def test_latest_week_before(store: Store) -> None:
    assert store.latest_week_before(SUN_18) is None
    store.record_action(date(2026, 10, 11), Action.FLAT_ASK, oct(6, 18))
    store.record_action(SUN_18, Action.FLAT_ASK, oct(13, 18))
    assert store.latest_week_before(SUN_18) == date(2026, 10, 11)
    assert store.latest_week_before(MON_19) == SUN_18
    assert store.has_any_action(SUN_18)
    assert not store.has_any_action(MON_19)


def test_upgrade_from_version_6_adds_the_applied_dinner(tmp_path: Path) -> None:
    path = tmp_path / "odin.db"
    conn = sqlite3.connect(path)
    conn.executescript(f"{'; '.join(_MIGRATIONS[:6])}; PRAGMA user_version = 6;")
    conn.close()
    with Store(path) as store:
        assert store.applied_dinner() is None
        store.set_applied_dinner("sun 18:00", SUN_18)
        assert store.applied_dinner() == AppliedDinner("sun 18:00", SUN_18)
        # There is only ever one; setting it again replaces it, without a held week.
        store.set_applied_dinner("mon 18:00")
        assert store.applied_dinner() == AppliedDinner("mon 18:00")


def test_unfinished_weeks_before(store: Store) -> None:
    sun_11 = date(2026, 10, 11)
    for action in Action:
        store.record_action(sun_11, action, oct(9, 14), Outcome.SKIPPED)
    store.record_action(SUN_18, Action.FLAT_ASK, oct(13, 18))
    store.record_dropped_week(MON_19, oct(18, 18))
    assert store.unfinished_weeks_before(MON_26) == [SUN_18, MON_19]
    assert store.unfinished_weeks_before(MON_19) == [SUN_18]
    store.record_action(MON_19, Action.TALLY, oct(20, 10), Outcome.SKIPPED)
    assert store.unfinished_weeks_before(MON_26) == [SUN_18]


# --- A new dinner weekday in the TOML (#81) -----------------------------------------------------

# The TOML before (dinner Sun 18:00) is CONFIG or SAT_COOK; these are the TOML after the edit.
TOML_SAT = make_config(
    schedule={"cook": {"weekday": "sat", "time": "17:00"}, "dinner": {"weekday": "sat"}}
)
TOML_MON = make_config(schedule={"dinner": {"weekday": "mon", "time": "18:00"}})
TOML_MON_SAT_COOK = make_config(
    schedule={"cook": {"weekday": "sat", "time": "17:00"}, "dinner": {"weekday": "mon"}}
)

SUNDAY_WEEK = [
    ("Tue 13.10. 18:00", "ASK Sonntag"),
    ("Wed 14.10. 18:00", "ESSEN Sonntag"),
    ("Fri 16.10. 14:00", "TALLY 1"),
]
SATURDAY_WEEKS = [
    ("Tue 20.10. 18:00", "ASK Samstag"),
    ("Wed 21.10. 18:00", "ESSEN Samstag"),
    ("Fri 23.10. 14:00", "TALLY 1"),
    ("Tue 27.10. 18:00", "ASK Samstag"),
    ("Wed 28.10. 18:00", "ESSEN Samstag"),
    ("Fri 30.10. 14:00", "TALLY 1"),
]
MONDAY_WEEKS = [
    ("Tue 20.10. 18:00", "ASK Montag"),
    ("Wed 21.10. 18:00", "ESSEN Montag"),
    ("Fri 23.10. 14:00", "TALLY 1"),
    ("Tue 27.10. 18:00", "ASK Montag"),
    ("Wed 28.10. 18:00", "ESSEN Montag"),
    ("Fri 30.10. 14:00", "TALLY 1"),
]


def runs(store: Store, *runs: tuple[Config, datetime, datetime]) -> list[tuple[str, str]]:
    """Run the bot from scratch for each (TOML, start, end) on the same DB, as after a restart
    with that TOML, and return everything sent across all of them."""
    sent = []
    for base, start, end in runs:
        bot = Bot(store, base)
        # Signal timestamps are wall-clock milliseconds, so a new client never reuses one.
        first = int(start.timestamp() * 1000)
        bot.client = FakeSignalClient(number=ACCOUNT.number, first_timestamp=first)
        bot.run(start, end)
        sent += bot.sent()
    return sent


def overrides_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "odin.overrides" and r.levelno >= logging.WARNING
    ]


def test_toml_sun_to_sat_on_wednesday_finishes_the_sunday_week(
    store: Store, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="odin.overrides"):
        sent = runs(
            store,
            (SAT_COOK, oct(12, 9), oct(14, 12)),  # the flat ask of Sun 18. is out
            (TOML_SAT, oct(14, 12), local(11, 1, 9)),  # restarted with Saturday in the TOML
        )
    assert sent == SUNDAY_WEEK + SATURDAY_WEEKS
    for week in (SUN_18, SAT_24, date(2026, 10, 31)):
        assert Bot(store, TOML_SAT).outcomes(week) == ALL_SENT
    # The Saturday "before" the switch never existed and is never touched.
    assert Bot(store, TOML_SAT).outcomes(date(2026, 10, 17)) == {}
    assert store.applied_dinner() == AppliedDinner("sat 18:00")
    # Warned once when the change was seen, once at the switch; not on every tick.
    assert overrides_warnings(caplog) == [
        "the config file moves dinner from sun 18:00 to sat 18:00; the running dinner week of "
        "2026-10-18 keeps sun 18:00, the new weekday takes over at its dinner "
        "(2026-10-18 18:00:00+02:00)",
        "dinner moves from sun 18:00 to sat 18:00 as the config file says, from the dinner "
        "week of 2026-10-24 on",
    ]


def test_toml_sun_to_mon_drops_the_cut_short_week_across_restarts(store: Store) -> None:
    sent = runs(
        store,
        (CONFIG, oct(12, 9), oct(15, 12)),
        # Restarted with Monday in the TOML on Thursday, and again on Saturday, at the switch
        # and just after it.
        (TOML_MON, oct(15, 12), oct(17, 9)),
        (TOML_MON, oct(17, 9), oct(18, 18)),
        (TOML_MON, oct(18, 18), oct(18, 18, 1)),
        (TOML_MON, oct(18, 18, 1), oct(18, 18, 2)),
        (TOML_MON, oct(18, 19), local(11, 3, 9)),
    )
    assert sent == [
        *SUNDAY_WEEK,
        ("Sun 18.10. 18:00", "ABGESAGT Montag"),  # Mon 19. is dropped; only its cancellation
        *MONDAY_WEEKS,
    ]
    bot = Bot(store, TOML_MON)
    assert bot.outcomes(SUN_18) == ALL_SENT
    assert bot.outcomes(MON_19) == DROPPED
    assert bot.outcomes(MON_26) == ALL_SENT
    assert bot.outcomes(date(2026, 10, 12)) == {}
    assert store.dropped_at(MON_19) == oct(18, 18).astimezone(UTC)


def test_toml_change_waits_after_the_first_record_of_the_week(store: Store) -> None:
    # Anything recorded makes the week a running one, even before its flat ask is due.
    store.set_applied_dinner("sun 18:00")
    store.record_action(SUN_18, Action.FLAT_ASK, oct(13, 9))
    config = effective_config(TOML_MON, store, oct(13, 10))
    assert config.schedule.dinner == CONFIG.schedule.dinner
    assert store.applied_dinner() == AppliedDinner("sun 18:00", SUN_18)


def test_toml_change_shows_in_schedule_and_status(store: Store) -> None:
    runs(store, (CONFIG, oct(12, 9), oct(15, 12)))
    lines = send(store, "/schedule", oct(15, 12), TOML_MON).splitlines()
    assert lines[6] == (
        "dinner – Essen: So 18:00 → ab 26.10.: Mo 18:00 (Mo 19.10. entfällt) (laut Config-Datei)"
    )
    status = send(store, "/status", oct(15, 12), TOML_MON).splitlines()
    assert status[0] == "Sonntag, 18.10."
    assert status[-2] == (
        "Ab Mo 26.10. ist das Essen montags um 18:00 (Mo 19.10. entfällt) (laut Config-Datei)."
    )
    assert status[-1] == "Nächste Aktion: Zählung, Fr 14:00"
    pending = pending_dinner(TOML_MON, store, oct(15, 12))
    assert pending is not None and pending.from_config
    assert (pending.after_week, pending.switch) == (SUN_18, oct(18, 18))


def test_resettime_explains_a_toml_change(store: Store) -> None:
    runs(store, (CONFIG, oct(12, 9), oct(15, 12)))
    reply = send(store, "/resettime dinner", oct(15, 12), TOML_MON)
    assert reply == "\n".join(
        [
            "Essen (dinner) war nicht geändert – steht auf So 18:00.",
            "Der Wechsel auf Mo 18:00 (ab Mo 26.10.) steht so in der Config-Datei. "
            "Um bei So 18:00 zu bleiben: /settime dinner sun 18:00",
        ]
    )
    assert pending_dinner(TOML_MON, store, oct(15, 13)) is not None


@pytest.mark.parametrize(
    ("toml", "expected"),
    [
        (
            TOML_SAT,
            [
                ("Tue 13.10. 18:00", "ASK Samstag"),  # Sat 17. is the first week
                ("Wed 14.10. 18:00", "ESSEN Samstag"),
                ("Fri 16.10. 14:00", "TALLY 1"),
                ("Tue 20.10. 18:00", "ASK Samstag"),
            ],
        ),
        (
            TOML_MON,
            [
                ("Sun 11.10. 19:00", "ABGESAGT Montag"),  # Mon 12. is dropped, at once
                ("Tue 13.10. 18:00", "ASK Montag"),
                ("Wed 14.10. 18:00", "ESSEN Montag"),
                ("Fri 16.10. 14:00", "TALLY 1"),
                ("Tue 20.10. 18:00", "ASK Montag"),
            ],
        ),
    ],
)
def test_toml_change_between_weeks_applies_at_once(
    store: Store, toml: Config, expected: list[tuple[str, str]]
) -> None:
    before = runs(store, (SAT_COOK, oct(5, 9), oct(11, 19)))  # after the dinner of Sun 11.
    assert [text for _, text in before] == ["ASK Sonntag", "ESSEN Sonntag", "TALLY 1"]
    assert effective_config(toml, store, oct(11, 19)) == toml
    assert pending_dinner(toml, store, oct(11, 19)) is None
    assert runs(store, (toml, oct(11, 19), oct(20, 19))) == expected
    assert store.applied_dinner() == AppliedDinner(format_weekly_time(toml.schedule.dinner))


def test_toml_change_after_a_missed_flat_ask_waits_like_a_chat_change(store: Store) -> None:
    # The bot was down over the flat ask of Sun 18.: nothing of that week was sent, but its flat
    # ask is due, so the week has started (the same rule as for `/settime dinner`). It keeps
    # Sunday; the missed ask is caught up within its window.
    runs(store, (SAT_COOK, oct(5, 9), oct(12, 9)))
    assert runs(store, (TOML_SAT, oct(14, 10), oct(21, 9))) == [
        ("Wed 14.10. 10:00", "ASK Sonntag"),  # caught up within its window
        ("Wed 14.10. 18:00", "ESSEN Sonntag"),
        ("Fri 16.10. 14:00", "TALLY 1"),
        ("Tue 20.10. 18:00", "ASK Samstag"),  # Sat 24. is the first Saturday week
    ]
    assert store.applied_dinner() == AppliedDinner("sat 18:00")


def test_toml_change_between_weeks_applies_at_once_before_the_flat_ask(store: Store) -> None:
    # Mon 12., after Sunday's dinner and before Tuesday's flat ask: nothing has started yet.
    runs(store, (SAT_COOK, oct(5, 9), oct(12, 9)))
    assert runs(store, (TOML_SAT, oct(12, 10), oct(14, 19))) == [
        ("Tue 13.10. 18:00", "ASK Samstag"),  # Sat 17. is the first week
        ("Wed 14.10. 18:00", "ESSEN Samstag"),
    ]
    assert Bot(store, TOML_SAT).outcomes(SUN_18) == {}


def test_toml_change_back_before_the_switch_changes_nothing(
    store: Store, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="odin.overrides"):
        sent = runs(
            store,
            (CONFIG, oct(12, 9), oct(15, 12)),
            (TOML_MON, oct(15, 12), oct(16, 9)),
            (CONFIG, oct(16, 9), oct(21, 9)),  # the TOML edit is undone on Friday
        )
    assert sent == [*SUNDAY_WEEK, ("Tue 20.10. 18:00", "ASK Sonntag")]
    assert store.applied_dinner() == AppliedDinner("sun 18:00")
    assert store.dropped_at(MON_19) is None
    warnings = overrides_warnings(caplog)
    assert len(warnings) == 2
    assert "is back on the weekday" in warnings[1]


def test_bot_down_over_a_toml_switch_finishes_every_open_week(store: Store) -> None:
    sent = runs(
        store,
        (CONFIG, oct(12, 9), oct(15, 12)),
        (TOML_MON, oct(15, 12), oct(16, 12)),
        # Down from Fri 16. 12:00, before the tally of Sun 18., until Tue 20. 10:00, after the
        # dinner of the dropped Mon 19.
        (TOML_MON, oct(20, 10), local(11, 3, 9)),
    )
    assert sent == [SUNDAY_WEEK[0], SUNDAY_WEEK[1], *MONDAY_WEEKS]
    bot = Bot(store, TOML_MON)
    assert bot.outcomes(SUN_18)[Action.TALLY] is Outcome.SKIPPED
    assert bot.outcomes(MON_19) == ALL_SKIPPED
    assert store.dropped_at(MON_19) == oct(18, 18).astimezone(UTC)  # the scheduled switch
    assert store.unfinished_weeks_before(date(2026, 11, 2)) == []


# --- A new weekday in the TOML and a pending chat change ----------------------------------------


def test_chat_change_wins_over_a_later_toml_change(store: Store) -> None:
    bot = Bot(store, SAT_COOK)
    bot.run(oct(12, 9), oct(16, 9), {oct(15, 12): "/settime dinner sat 18:00"})
    # Restarted on Friday with Monday in the TOML: the chat change is still the pending one.
    pending = pending_dinner(TOML_MON_SAT_COOK, store, oct(16, 9))
    assert pending is not None and not pending.from_config
    sent = bot.sent() + runs(store, (TOML_MON_SAT_COOK, oct(16, 9), local(11, 3, 9)))
    assert sent == SUNDAY_WEEK + SATURDAY_WEEKS
    assert stored(store) == {DINNER_KEY: ("sat 18:00", None)}
    assert store.applied_dinner() == AppliedDinner("sat 18:00")
    for week in (MON_19, MON_26):
        assert store.dropped_at(week) is None
        assert Bot(store, TOML_MON_SAT_COOK).outcomes(week) == {}


def test_chat_change_wins_over_a_waiting_toml_change(store: Store) -> None:
    runs(store, (SAT_COOK, oct(12, 9), oct(15, 12)), (TOML_MON_SAT_COOK, oct(15, 12), oct(16, 9)))
    reply = send(store, "/settime dinner sat 18:00", oct(16, 9), TOML_MON_SAT_COOK)
    assert reply.splitlines()[1:3] == [
        "Essen (dinner): So 18:00 → Sa 18:00",
        "Das gilt ab dem Essen am Sa 24.10. um 18:00. "
        "Diese Woche bleibt es beim Essen am So 18.10. um 18:00.",
    ]
    pending = pending_dinner(TOML_MON_SAT_COOK, store, oct(16, 10))
    assert pending is not None and pending.point == WeeklyTime(5, time(18))
    sent = runs(store, (TOML_MON_SAT_COOK, oct(16, 9), local(11, 3, 9)))
    assert sent == [SUNDAY_WEEK[2], *SATURDAY_WEEKS]
    assert store.dropped_at(MON_19) is None


def test_resetting_the_chat_change_brings_back_the_toml_change(store: Store) -> None:
    runs(store, (SAT_COOK, oct(12, 9), oct(15, 12)), (TOML_MON_SAT_COOK, oct(15, 12), oct(16, 9)))
    send(store, "/settime dinner sat 18:00", oct(16, 9), TOML_MON_SAT_COOK)
    reply = send(store, "/resettime dinner", oct(16, 10), TOML_MON_SAT_COOK)
    assert reply.splitlines()[0] == (
        "Verworfen ✅ Der geplante Wechsel auf Sa 18:00 (ab Sa 24.10.) fällt weg."
    )
    assert reply.splitlines()[-1].startswith("Der Wechsel auf Mo 18:00 (ab Mo 26.10.) steht so")
    pending = pending_dinner(TOML_MON_SAT_COOK, store, oct(16, 10))
    assert pending is not None and pending.from_config


def test_chat_can_keep_the_weekday_against_the_toml(store: Store) -> None:
    runs(store, (CONFIG, oct(12, 9), oct(15, 12)))
    reply = send(store, "/settime dinner sun 18:00", oct(15, 12), TOML_MON)
    assert reply.splitlines()[-1] == (
        "Der geplante Wechsel auf Mo 18:00 (ab Mo 26.10.) ist damit verworfen."
    )
    assert pending_dinner(TOML_MON, store, oct(15, 13)) is None
    sent = runs(store, (TOML_MON, oct(15, 12), oct(21, 9)))
    assert sent == [SUNDAY_WEEK[2], ("Tue 20.10. 18:00", "ASK Sonntag")]
    assert store.applied_dinner() == AppliedDinner("sun 18:00")


# --- A new weekday in the TOML on the first start after the upgrade -----------------------------


def test_first_start_keeps_the_weekday_of_a_running_week(store: Store) -> None:
    # A DB from before the applied dinner was stored, with the week of Sun 18. started.
    store.record_action(SUN_18, Action.FLAT_ASK, oct(13, 18))
    config = effective_config(TOML_MON, store, oct(15, 12))
    assert config.schedule.dinner == CONFIG.schedule.dinner  # TOML_MON's time, on Sunday
    assert store.applied_dinner() == AppliedDinner("sun 18:00", SUN_18)


def test_first_start_takes_the_effective_dinner(store: Store) -> None:
    store.record_action(date(2026, 10, 11), Action.TALLY, oct(9, 14))
    assert effective_config(TOML_MON, store, oct(12, 9)) == TOML_MON
    assert store.applied_dinner() == AppliedDinner("mon 18:00")


@pytest.mark.parametrize("chat_pending", [False, True])
def test_other_schedule_changes_work_while_a_toml_change_waits(
    store: Store, chat_pending: bool
) -> None:
    runs(store, (SAT_COOK, oct(12, 9), oct(15, 12)), (TOML_MON_SAT_COOK, oct(15, 12), oct(15, 13)))
    if chat_pending:
        send(store, "/settime dinner sat 18:00", oct(15, 13), TOML_MON_SAT_COOK)
    reply = send(store, "/settime tally fri 15:00", oct(15, 14), TOML_MON_SAT_COOK)
    assert reply.splitlines()[:3] == [
        SAVED,
        "Zählung der Gäste (tally): Fr 15:00, nächstes Mal Fr 16.10. um 15:00",
        "Das gilt schon für diese Woche.",
    ]
    config = effective_config(TOML_MON_SAT_COOK, store, oct(15, 14))
    assert config.schedule.dinner == CONFIG.schedule.dinner  # still Sunday this week
    assert config.schedule.tally == WeeklyTime(4, time(15))
    pending = pending_dinner(TOML_MON_SAT_COOK, store, oct(15, 14))
    assert pending is not None and pending.from_config is not chat_pending
    assert send(store, "/nudge off", oct(15, 14), TOML_MON_SAT_COOK).startswith(SAVED)
