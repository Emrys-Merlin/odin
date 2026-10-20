"""/status: where the current dinner week stands, and what ODIN does next.

Reads the store only; never writes. Works on the effective config (`ctx.config`), plus a pending
dinner weekday change (`odin.overrides.pending_dinner`), which takes over at this week's dinner.
A week cancelled via /cancel shows the cancellation (after the announcement, if that was sent),
and an open cancel request shows whether it is confirmed yet. A skip date (`/skip`) shows as a
week without flat ask whose cancellation goes out at the decision time; later skip dates are
listed.
"""

import dataclasses
from datetime import UTC, date, datetime, timedelta
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
from odin.cycle import StepName
from odin.store import Action, MessageKind, Outcome, Store

if TYPE_CHECKING:
    from odin.engine import Upcoming
    from odin.overrides import PendingDinner

# German labels for the steps.
FLAT_ASK = "Frage an die WG"
NUDGE = "Erinnerung"
DECISION = "Entscheidung"
TALLY = "Zählung"
STEP_LABELS = {
    StepName.FLAT_ASK: FLAT_ASK,
    StepName.NUDGE: NUDGE,
    StepName.DECISION: DECISION,
    StepName.TALLY: TALLY,
}

SENT = "✅"
CANCELLED = "❌"
SKIPPED = "⏭️"
PENDING = "⏳"
OFF = "–"
ONLY_IF_UNCONFIRMED = "nur falls noch kein {emoji}"
NO_DINNER = "kein Essen"
ASKED_AGAIN = "nochmal gefragt"
REQUESTED = "🛑 Absage per /cancel angefragt ({at})"
AWAITING = "wartet auf {emoji}"
CONFIRMED = "bestätigt, geht gleich raus"
BY_CANCEL = "per /cancel"
CANCELLATION_NOW = "Absage an die Essensgruppe, gleich"
BY_SKIP = "per /skip"
DROPPED_STEP = "entfällt ({reason})"
CANCELLATION_STEP = "Absage an die Essensgruppe"
LATER_SKIPS = "Kein Essen per /skip: {days}"
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
    later = store.skip_dates(since=week + timedelta(days=1))
    if later:
        lines.append(LATER_SKIPS.format(days=", ".join(ui.short_date(s.day) for s in later)))
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
    def cancelled(self) -> bool:
        return self.outcome(Action.CANCELLATION) is Outcome.SENT

    @property
    def dinner_on(self) -> bool:
        return self.outcome(Action.ANNOUNCEMENT) is Outcome.SENT and not self.cancelled

    @property
    def skipping(self) -> bool:
        return _skipping(self.store, self.week)

    @property
    def cancel_confirmed(self) -> bool:
        """Whether a /cancel request of this week has its confirming reaction."""
        return (self._count(MessageKind.CANCEL_REQUEST) or 0) > 0

    @property
    def cancel_pending(self) -> bool:
        """A confirmed /cancel whose cancellation the engine sends on its next tick."""
        return self.cancel_confirmed and self.outcome(Action.CANCELLATION) is None

    def confirmations(self) -> int:
        return self._count(MessageKind.FLAT_POLL) or 0

    def lines(self) -> list[str]:
        schedule = self.config.schedule

        off = f"{OFF} {{label}}: " + DROPPED_STEP.format(reason=BY_SKIP)
        if self.skipping and self.outcome(Action.FLAT_ASK) is None:
            flat_ask = off.format(label=FLAT_ASK)
        else:
            flat_ask = self._step(
                Action.FLAT_ASK, FLAT_ASK, "Frage an die WG gesendet", schedule.flat_ask
            )
        if self.asked:
            if self.outcome(Action.FLAT_ASK_RETRY) is Outcome.SENT:
                flat_ask += f", {ASKED_AGAIN} ({self._sent_at(Action.FLAT_ASK_RETRY)})"
            flat_ask += " – " + self._reactions(MessageKind.FLAT_POLL)

        if schedule.nudge is None and self.outcome(Action.NUDGE) is None:
            nudge = f"{OFF} {NUDGE}: aus"
        elif self.skipping and self.outcome(Action.NUDGE) is None:
            nudge = off.format(label=NUDGE)
        else:
            nudge = self._step(Action.NUDGE, NUDGE, "Erinnerung gesendet", schedule.nudge_time)

        decisions = []
        cancellation = ""
        if self.cancelled:
            cancellation = f"{CANCELLED} Absage gesendet ({self._sent_at(Action.CANCELLATION)})"
            if self.cancel_confirmed:
                cancellation += f" – {BY_CANCEL}"
            elif self.skipping:
                cancellation += f" – {BY_SKIP}"
        if self.outcome(Action.ANNOUNCEMENT) is Outcome.SENT:
            decision = f"{SENT} Einladung gesendet ({self._sent_at(Action.ANNOUNCEMENT)})"
            decision += " – " + self._reactions(MessageKind.DINNER_ANNOUNCEMENT)
            if cancellation:  # cancelled via /cancel after the announcement
                decisions.append(cancellation)
        elif self.cancelled:
            decision = cancellation
        elif self.decided:
            decision = f"{SKIPPED} {DECISION}: übersprungen"
        elif self.skipping:
            when = ui.weekly_time(schedule.flat_deadline)
            decision = f"{PENDING} {CANCELLATION_STEP}: {when} – {BY_SKIP}"
        else:
            decision = f"{PENDING} {DECISION}: {ui.weekly_time(schedule.flat_deadline)}"

        request = self.store.tracked_message(self.week, MessageKind.CANCEL_REQUEST)
        if request is not None and self.outcome(Action.CANCELLATION) is None:
            at = datetime.fromtimestamp(request.timestamp / 1000, UTC)
            line = REQUESTED.format(at=self._local(at))
            awaiting = AWAITING.format(emoji=self.config.emoji)
            state = CONFIRMED if self.cancel_confirmed else awaiting
            decisions.append(f"{line} – {state}")

        if self.outcome(Action.TALLY) is None and (
            (self.decided and not self.dinner_on) or self.skipping
        ):
            tally = f"{OFF} {TALLY}: entfällt ({NO_DINNER})"
        elif self.outcome(Action.TALLY) is Outcome.SKIPPED and not self.dinner_on:
            tally = f"{SKIPPED} {TALLY}: übersprungen ({NO_DINNER})"
        else:
            tally = self._step(Action.TALLY, TALLY, "Zählung gesendet", schedule.tally)

        return [flat_ask, nudge, decision, *decisions, tally]

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
        return self._local(at)

    def _local(self, at: datetime) -> str:
        local = at.astimezone(self.config.timezone)
        return f"{ui.WEEKDAYS_SHORT[local.weekday()]} {local:%H:%M}"

    def _reactions(self, kind: MessageKind) -> str:
        """``2× 👍``, or that they cannot be counted: the message was sent but is not tracked."""
        count = self._count(kind)
        emoji = self.config.emoji
        return ui.UNTRACKED.format(emoji=emoji) if count is None else f"{count}× {emoji}"

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

    if current.cancel_pending:
        return CANCELLATION_NOW
    flat_ask_missed = current.outcome(Action.FLAT_ASK) is None and (
        engine.step_windows(config, current.week)[0].due(now) is False
    )
    # If every step still ahead belongs to this week and none of them will happen (e.g. it was
    # cancelled before its flat ask), the next action is next week's first.
    dinner = config.when(config.schedule.dinner, current.week)
    candidates = [*_upcoming(config, now, pending), *_upcoming(config, dinner, pending)]
    for upcoming in candidates:
        note = ""
        label = STEP_LABELS[upcoming.step]
        if _skipping(current.store, upcoming.week):
            # No flat ask, nudge or tally; the cancellation goes out at the decision time.
            if upcoming.step is not StepName.DECISION or (
                upcoming.week == current.week and current.decided
            ):
                continue
            label = CANCELLATION_STEP
        elif engine.dinner_week(config, upcoming.at) == current.week:
            match upcoming.step:
                case StepName.FLAT_ASK:
                    if current.outcome(Action.FLAT_ASK) is not None:
                        continue
                case StepName.NUDGE:
                    if current.outcome(Action.NUDGE) is not None or (
                        current.asked and current.confirmations() > 0
                    ):
                        continue
                    note = ONLY_IF_UNCONFIRMED.format(emoji=config.emoji)
                case StepName.DECISION:
                    if current.decided:
                        continue
                case StepName.TALLY:
                    if current.outcome(Action.TALLY) is not None or (
                        current.decided and not current.dinner_on
                    ):
                        continue
            # Without a flat ask nobody can confirm: the rest of the week is skipped. That is also
            # so for a flat ask past its window, e.g. of a week dropped by a weekday change.
            if current.outcome(Action.FLAT_ASK) is Outcome.SKIPPED or flat_ask_missed:
                continue
        elif upcoming.step is StepName.NUDGE:
            note = ONLY_IF_UNCONFIRMED.format(emoji=config.emoji)
        at = upcoming.at.astimezone(config.timezone)
        text = f"{label}, {ui.WEEKDAYS_SHORT[at.weekday()]} {at:%H:%M}"
        return f"{text} ({note})" if note else text
    return None


def _skipping(store: Store, week: date) -> bool:
    """Whether `week` is a skip date that is in effect: its flat ask has not gone out."""
    return store.skip_date(week) is not None and (
        store.action_outcome(week, Action.FLAT_ASK) is not Outcome.SENT
    )


STATUS = Command(
    name="status",
    usage="/status",
    summary="Zeigt den Stand dieser Woche und die nächste Aktion.",
    run=run,
)
