"""/status: where the current dinner week stands, and what ODIN does next.

Reads the store only; never writes. Works on the effective config (`ctx.config`), plus a pending
dinner weekday change (`odin.overrides.pending_dinner`), which takes over at this week's dinner.
"""

import dataclasses
from datetime import date, datetime
from typing import TYPE_CHECKING

# odin.engine (and odin.overrides, which imports it) is imported inside the functions and
# odin.reactions as a module: engine imports reactions, whose event consumer dispatches to
# odin.commands, which imports this module, so importing engine or names from reactions here
# would close an import cycle.
from odin import reactions
from odin.commands import ui
from odin.commands.core import Command, CommandContext
from odin.commands.schedule import DROPPED, FROM_CONFIG
from odin.config import WEEKDAYS_DE, Config, WeeklyTime
from odin.store import Action, MessageKind, Outcome, Store

if TYPE_CHECKING:
    from odin.engine import Upcoming
    from odin.overrides import PendingDinner

# German labels for the steps, keyed by the names `upcoming_actions` uses.
FLAT_ASK = "Frage an die WG"
NUDGE = "Erinnerung"
DECISION = "Entscheidung"
TALLY = "Zählung"
STEP_LABELS = {
    "flat ask": FLAT_ASK,
    "nudge": NUDGE,
    "announcement / cancellation": DECISION,
    "tally": TALLY,
}

SENT = "✅"
CANCELLED = "❌"
SKIPPED = "⏭️"
PENDING = "⏳"
OFF = "–"
ONLY_IF_UNCONFIRMED = "nur falls noch kein {emoji}"
NO_DINNER = "kein Essen"
UNTRACKED = "{emoji} nicht zählbar"
ASKED_AGAIN = "nochmal gefragt"
PENDING_DINNER = "Ab {weekday} {first:%d.%m.} ist das Essen {weekdays} um {time:%H:%M}"


def run(ctx: CommandContext, args: str) -> list[str]:
    from odin.overrides import pending_dinner

    pending = pending_dinner(ctx.base, ctx.store, ctx.now)
    return [status(ctx.config, ctx.store, ctx.now, pending)]


def status(
    config: Config, store: Store, now: datetime, pending: PendingDinner | None = None
) -> str:
    from odin import engine

    week = engine.dinner_week(config, now)
    week_status = _WeekStatus(config, store, week)
    lines = [f"{WEEKDAYS_DE[week.weekday()]}, {week:%d.%m.}", *week_status.lines()]
    if pending is not None:
        lines.append(_pending_line(pending))
    following = _next_action(config, week_status, now, pending)
    if following:
        lines.append(f"Nächste Aktion: {following}")
    return "\n".join(lines)


class _WeekStatus:
    """The recorded state of one dinner week, rendered line by line."""

    def __init__(self, config: Config, store: Store, week: date) -> None:
        self.config = config
        self.store = store
        self.week = week

    def outcome(self, action: Action) -> Outcome | None:
        return self.store.action_outcome(self.week, action)

    @property
    def asked(self) -> bool:
        return self.outcome(Action.FLAT_ASK) is Outcome.SENT

    @property
    def decided(self) -> bool:
        return self.outcome(Action.ANNOUNCEMENT) is not None or (
            self.outcome(Action.CANCELLATION) is not None
        )

    @property
    def dinner_on(self) -> bool:
        return self.outcome(Action.ANNOUNCEMENT) is Outcome.SENT

    def confirmations(self) -> int:
        return self._count(MessageKind.FLAT_POLL) or 0

    def lines(self) -> list[str]:
        schedule = self.config.schedule

        flat_ask = self._step(
            Action.FLAT_ASK, FLAT_ASK, "Frage an die WG gesendet", schedule.flat_ask
        )
        if self.asked:
            if self.outcome(Action.FLAT_ASK_RETRY) is Outcome.SENT:
                flat_ask += f", {ASKED_AGAIN} ({self._sent_at(Action.FLAT_ASK_RETRY)})"
            flat_ask += " – " + self._reactions(MessageKind.FLAT_POLL)

        if schedule.nudge is None and self.outcome(Action.NUDGE) is None:
            nudge = f"{OFF} {NUDGE}: aus"
        else:
            nudge = self._step(Action.NUDGE, NUDGE, "Erinnerung gesendet", schedule.nudge_time)

        if self.outcome(Action.ANNOUNCEMENT) is Outcome.SENT:
            decision = f"{SENT} Einladung gesendet ({self._sent_at(Action.ANNOUNCEMENT)})"
            decision += " – " + self._reactions(MessageKind.DINNER_ANNOUNCEMENT)
        elif self.outcome(Action.CANCELLATION) is Outcome.SENT:
            decision = f"{CANCELLED} Absage gesendet ({self._sent_at(Action.CANCELLATION)})"
        elif self.decided:
            decision = f"{SKIPPED} {DECISION}: übersprungen"
        else:
            decision = f"{PENDING} {DECISION}: {ui.weekly_time(schedule.flat_deadline)}"

        if self.outcome(Action.TALLY) is None and self.decided and not self.dinner_on:
            tally = f"{OFF} {TALLY}: entfällt ({NO_DINNER})"
        elif self.outcome(Action.TALLY) is Outcome.SKIPPED and not self.dinner_on:
            tally = f"{SKIPPED} {TALLY}: übersprungen ({NO_DINNER})"
        else:
            tally = self._step(Action.TALLY, TALLY, "Zählung gesendet", schedule.tally)

        return [flat_ask, nudge, decision, tally]

    def _step(self, action: Action, label: str, sent: str, point: WeeklyTime) -> str:
        match self.outcome(action):
            case Outcome.SENT:
                return f"{SENT} {sent} ({self._sent_at(action)})"
            case Outcome.SKIPPED:
                return f"{SKIPPED} {label}: übersprungen"
            case None:
                return f"{PENDING} {label}: {ui.weekly_time(point)}"

    def _sent_at(self, action: Action) -> str:
        at = self.store.action_time(self.week, action)
        assert at is not None
        local = at.astimezone(self.config.timezone)
        return f"{ui.WEEKDAYS_SHORT[local.weekday()]} {local:%H:%M}"

    def _reactions(self, kind: MessageKind) -> str:
        """``2× 👍``, or that they cannot be counted: the message was sent but is not tracked."""
        count = self._count(kind)
        emoji = self.config.emoji
        return UNTRACKED.format(emoji=emoji) if count is None else f"{count}× {emoji}"

    def _count(self, kind: MessageKind) -> int | None:
        """The reactions on the week's message of `kind`; None if it is not tracked."""
        message = self.store.tracked_message(self.week, kind)
        if message is None:
            return None
        return reactions.count_confirmations(self.store, message, self.config.emoji)


def _pending_line(pending: PendingDinner) -> str:
    """``Ab Sa 24.10. ist das Essen samstags um 18:00.``, with a dropped week as in /schedule."""
    first = pending.transition.first_week
    line = PENDING_DINNER.format(
        weekday=ui.WEEKDAYS_SHORT[first.weekday()],
        first=first,
        weekdays=WEEKDAYS_DE[pending.point.weekday].lower() + "s",
        time=pending.point.time,
    )
    dropped = pending.transition.dropped_week
    if dropped is not None:
        weekday = ui.WEEKDAYS_SHORT[dropped.weekday()]
        line += " " + DROPPED.format(weekday=weekday, day=dropped)
    if pending.from_config:
        line += " " + FROM_CONFIG
    return line + "."


def _upcoming(config: Config, now: datetime, pending: PendingDinner | None) -> list[Upcoming]:
    """The scheduled actions from `now` on, in time order, across a pending weekday change.

    Before the switch they come from the current schedule, from it on from the new schedule's
    first week. A week dropped by the switch has all its steps before it, so none is listed.
    """
    from odin import engine

    upcoming = engine.upcoming_actions(config, now)
    if pending is None:
        return upcoming
    new = dataclasses.replace(
        config, schedule=dataclasses.replace(config.schedule, dinner=pending.point)
    )
    # The flat ask opens a week, so from it on the next occurrences are that week's steps.
    first_ask = new.when(new.schedule.flat_ask, pending.transition.first_week)
    return [u for u in upcoming if u.at < pending.switch] + engine.upcoming_actions(new, first_ask)


def _next_action(
    config: Config, current: _WeekStatus, now: datetime, pending: PendingDinner | None
) -> str | None:
    """The first scheduled action that will (or may) still happen, in German."""
    from odin import engine

    flat_ask_missed = current.outcome(Action.FLAT_ASK) is None and (
        engine.step_windows(config, current.week)[0].due(now) is False
    )
    for upcoming in _upcoming(config, now, pending):
        note = ""
        if engine.dinner_week(config, upcoming.at) == current.week:
            match upcoming.name:
                case "flat ask":
                    if current.outcome(Action.FLAT_ASK) is not None:
                        continue
                case "nudge":
                    if current.outcome(Action.NUDGE) is not None or (
                        current.asked and current.confirmations() > 0
                    ):
                        continue
                    note = ONLY_IF_UNCONFIRMED.format(emoji=config.emoji)
                case "announcement / cancellation":
                    if current.decided:
                        continue
                case "tally":
                    if current.outcome(Action.TALLY) is not None or (
                        current.decided and not current.dinner_on
                    ):
                        continue
            # Without a flat ask nobody can confirm: the rest of the week is skipped. That is also
            # so for a flat ask past its window, e.g. of a week dropped by a weekday change.
            if current.outcome(Action.FLAT_ASK) is Outcome.SKIPPED or flat_ask_missed:
                continue
        elif upcoming.name == "nudge":
            note = ONLY_IF_UNCONFIRMED.format(emoji=config.emoji)
        at = upcoming.at.astimezone(config.timezone)
        text = f"{STEP_LABELS[upcoming.name]}, {ui.WEEKDAYS_SHORT[at.weekday()]} {at:%H:%M}"
        return f"{text} ({note})" if note else text
    return None


STATUS = Command(
    name="status",
    usage="/status",
    summary="Zeigt den Stand dieser Woche und die nächste Aktion.",
    run=run,
)
