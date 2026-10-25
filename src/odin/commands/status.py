"""/status: where the current dinner week stands, and what ODIN does next.

Reads the store only; never writes. Works on the effective config (`ctx.config`), plus a pending
dinner weekday change (`odin.overrides.pending_dinner`), which takes over at this week's dinner.
A week cancelled via /cancel shows the cancellation (after the announcement, if that was sent),
and an open cancel request shows whether it is confirmed yet. A skip date (`/skip`) shows as a
week without flat ask whose cancellation goes out at the decision time; later skip dates are
listed. While the cancellation is switched off (`/cancellation off`), the pending decision says
so, and a cancellation that was not posted because of it shows as such. During a hiatus
(`/hiatus`) the hiatus is shown — since when, by whom, its notice and how to end it — instead of
the next action, and a week that is part of a hiatus shows no steps.
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
from odin.store import Action, Hiatus, MessageKind, Outcome, Store

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
BY_HIATUS = "per /hiatus"
HIATUS_WEEK = "😴 Kein Essen – Pause per /hiatus"
HIATUS_SINCE = "😴 Pause seit {at} (von {by}): keine Frage an die WG, nichts an die Essensgruppe."
HIATUS_REQUESTED = "😴 Pause per /hiatus angefragt ({at}) – {state}"
HIATUS_CONFIRMED = "bestätigt, beginnt gleich"
NOTICE = "Hinweis an die Essensgruppe"
CANCELLATION_OFF = "Absage an die Essensgruppe: aus"
SILENCED = "nicht gesendet (aus)"
NOTICE_SILENCED = "nicht gesendet (Absage ist aus)"


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
    lines = [f"{WEEKDAYS_DE[week.weekday()]}, {week:%d.%m.}"]
    if store.hiatus_covering(week) is not None:
        lines.append(HIATUS_WEEK)
    else:
        lines += week_status.lines()
    request = _hiatus_request_line(config, store, week)
    if request is not None:
        lines.append(request)
    active = store.active_hiatus()
    if active is not None:
        lines += _hiatus_lines(config, active)
    later = store.skip_dates(since=week + timedelta(days=1))
    if later:
        lines.append(LATER_SKIPS.format(days=", ".join(ui.short_date(s.day) for s in later)))
    if pending is not None:
        lines.append(_pending_line(pending))
    if active is not None:
        lines.append(ui.RESUME_HINT)
        return "\n".join(lines)
    following = _next_action(config, week_status, now, pending)
    if following:
        lines.append(f"Nächste Aktion: {following}")
    return "\n".join(lines)


def _hiatus_lines(config: Config, hiatus: Hiatus) -> list[str]:
    """Since when and by whom ODIN sleeps, and its notice to the dinner group."""
    assert hiatus.started_at is not None
    since = HIATUS_SINCE.format(at=_local_date(config, hiatus.started_at), by=hiatus.requested_by)
    match hiatus.notice:
        case Outcome.SENT:
            assert hiatus.notice_at is not None
            notice = f"{SENT} {NOTICE} gesendet ({_local_date(config, hiatus.notice_at)})"
        case Outcome.SKIPPED:
            notice = f"{SKIPPED} {NOTICE}: übersprungen"
        case Outcome.SILENCED:
            notice = f"{OFF} {NOTICE}: {NOTICE_SILENCED}"
        case None:
            notice = f"{PENDING} {NOTICE}: gleich"
    return [since, notice]


def _hiatus_request_line(config: Config, store: Store, week: date) -> str | None:
    """An open /hiatus request of `week`, and whether it is confirmed yet."""
    request = store.tracked_message(week, MessageKind.HIATUS_REQUEST)
    if request is None:
        return None
    at = datetime.fromtimestamp(request.timestamp / 1000, UTC)
    confirmed = reactions.count_confirmations(store, request, config.emoji) > 0
    state = HIATUS_CONFIRMED if confirmed else AWAITING.format(emoji=config.emoji)
    return HIATUS_REQUESTED.format(at=_local_date(config, at), state=state)


def _local_date(config: Config, at: datetime) -> str:
    return ui.moment(at, config.timezone)


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
        """The lines of the week's steps: flat ask, nudge, decision (with a /cancel), tally."""
        return [
            self._flat_ask_line(),
            self._nudge_line(),
            *self._decision_lines(),
            self._tally_line(),
        ]

    def _flat_ask_line(self) -> str:
        """The flat ask; once sent, with a second ask and the confirmations on it."""
        if self.skipping and self.outcome(Action.FLAT_ASK) is None:
            return self._dropped_by_skip(FLAT_ASK)
        line = self._step(
            Action.FLAT_ASK, FLAT_ASK, "Frage an die WG gesendet", self.config.schedule.flat_ask
        )
        if self.asked:
            if self.outcome(Action.FLAT_ASK_RETRY) is Outcome.SENT:
                line += f", {ASKED_AGAIN} ({self._sent_at(Action.FLAT_ASK_RETRY)})"
            line += " – " + self._reactions(MessageKind.FLAT_POLL)
        return line

    def _nudge_line(self) -> str:
        """The nudge: off, dropped by a skip date, or its step."""
        schedule = self.config.schedule
        if schedule.nudge is None and self.outcome(Action.NUDGE) is None:
            return f"{OFF} {NUDGE}: aus"
        if self.skipping and self.outcome(Action.NUDGE) is None:
            return self._dropped_by_skip(NUDGE)
        return self._step(Action.NUDGE, NUDGE, "Erinnerung gesendet", schedule.nudge_time)

    def _decision_lines(self) -> list[str]:
        """The decision; then a cancellation via /cancel after the announcement, and an open
        /cancel request."""
        lines = [self._decision_line()]
        if self.outcome(Action.ANNOUNCEMENT) is Outcome.SENT and self.cancelled:
            lines.append(self._cancellation_line())
        request = self._cancel_request_line()
        if request is not None:
            lines.append(request)
        return lines

    def _decision_line(self) -> str:
        """The announcement with its RSVPs, the cancellation, or the decision still ahead."""
        if self.outcome(Action.ANNOUNCEMENT) is Outcome.SENT:
            line = f"{SENT} Einladung gesendet ({self._sent_at(Action.ANNOUNCEMENT)})"
            return line + " – " + self._reactions(MessageKind.DINNER_ANNOUNCEMENT)
        if self.cancelled:
            return self._cancellation_line()
        if self.outcome(Action.CANCELLATION) is Outcome.SILENCED:
            line = f"{OFF} {CANCELLATION_STEP}: {SILENCED}"
            return f"{line} – {BY_SKIP}" if self.skipping else line
        if self.decided:
            return f"{SKIPPED} {DECISION}: übersprungen"
        when = ui.weekly_time(self.config.schedule.flat_deadline)
        if self.skipping:
            if not self.config.decision.cancellation:
                return f"{OFF} {CANCELLATION_OFF} – {BY_SKIP}"
            return f"{PENDING} {CANCELLATION_STEP}: {when} – {BY_SKIP}"
        if not self.config.decision.cancellation:
            return f"{PENDING} {DECISION}: {when} ({CANCELLATION_OFF})"
        return f"{PENDING} {DECISION}: {when}"

    def _cancellation_line(self) -> str:
        """The sent cancellation, and whether /cancel or /skip caused it."""
        from odin import engine

        line = f"{CANCELLED} Absage gesendet ({self._sent_at(Action.CANCELLATION)})"
        if self.cancel_confirmed:
            return f"{line} – {BY_CANCEL}"
        if engine.cancelled_by_hiatus(self.store, self.week):
            return f"{line} – {BY_HIATUS}"
        if self.skipping:
            return f"{line} – {BY_SKIP}"
        return line

    def _cancel_request_line(self) -> str | None:
        """A /cancel request whose cancellation is not sent yet, and whether it is confirmed."""
        request = self.store.tracked_message(self.week, MessageKind.CANCEL_REQUEST)
        if request is None or self.outcome(Action.CANCELLATION) is not None:
            return None
        at = datetime.fromtimestamp(request.timestamp / 1000, UTC)
        line = REQUESTED.format(at=self._local(at))
        awaiting = AWAITING.format(emoji=self.config.emoji)
        state = CONFIRMED if self.cancel_confirmed else awaiting
        return f"{line} – {state}"

    def _tally_line(self) -> str:
        """The tally: dropped or skipped without a dinner, else its step."""
        if self.outcome(Action.TALLY) is None and (
            (self.decided and not self.dinner_on) or self.skipping
        ):
            return f"{OFF} {TALLY}: entfällt ({NO_DINNER})"
        if self.outcome(Action.TALLY) is Outcome.SKIPPED and not self.dinner_on:
            return f"{SKIPPED} {TALLY}: übersprungen ({NO_DINNER})"
        return self._step(Action.TALLY, TALLY, "Zählung gesendet", self.config.schedule.tally)

    def _dropped_by_skip(self, label: str) -> str:
        return f"{OFF} {label}: " + DROPPED_STEP.format(reason=BY_SKIP)

    def _step(self, action: Action, label: str, sent: str, point: WeeklyTime) -> str:
        match self.outcome(action):
            case Outcome.SENT:
                return f"{SENT} {sent} ({self._sent_at(action)})"
            case Outcome.SKIPPED | Outcome.SILENCED:
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
        if current.store.hiatus_covering(upcoming.week) is not None:
            continue  # nothing is sent in a week that is part of a hiatus
        if _skipping(current.store, upcoming.week):
            # No flat ask, nudge or tally; the cancellation goes out at the decision time.
            if _skip_cancellation_ahead(current, upcoming):
                return _action_line(config, upcoming, CANCELLATION_STEP)
        elif engine.dinner_week(config, upcoming.at) != current.week or (
            _step_ahead(current, upcoming.step, flat_ask_missed)
        ):
            return _action_line(config, upcoming)
    return None


def _skip_cancellation_ahead(current: _WeekStatus, upcoming: Upcoming) -> bool:
    """Whether `upcoming`, in a week with a skip date, is a cancellation still to be sent: its
    decision step, unless that is this week's and already decided, or the cancellation is off."""
    return (
        upcoming.step is StepName.DECISION
        and current.config.decision.cancellation
        and not (upcoming.week == current.week and current.decided)
    )


def _step_ahead(current: _WeekStatus, step: StepName, flat_ask_missed: bool) -> bool:
    """Whether `step` of the current week will (or may) still happen."""
    # Without a flat ask nobody can confirm: the rest of the week is skipped. That is also so for
    # a flat ask past its window, e.g. of a week dropped by a weekday change.
    no_flat_ask = current.outcome(Action.FLAT_ASK) is Outcome.SKIPPED or flat_ask_missed
    return not (_step_settled(current, step) or no_flat_ask)


def _step_settled(current: _WeekStatus, step: StepName) -> bool:
    """Whether `step` of the current week has happened or no longer will, by its own state."""
    match step:
        case StepName.FLAT_ASK:
            return current.outcome(Action.FLAT_ASK) is not None
        case StepName.NUDGE:
            return current.outcome(Action.NUDGE) is not None or (
                current.asked and current.confirmations() > 0
            )
        case StepName.DECISION:
            return current.decided
        case StepName.TALLY:
            return current.outcome(Action.TALLY) is not None or (
                current.decided and not current.dinner_on
            )


def _action_line(config: Config, upcoming: Upcoming, label: str | None = None) -> str:
    """``Erinnerung, Mi 12:00 (nur falls noch kein 👍)``: the step (or `label`) and its time."""
    if label is None:
        label = STEP_LABELS[upcoming.step]
    at = upcoming.at.astimezone(config.timezone)
    text = f"{label}, {ui.WEEKDAYS_SHORT[at.weekday()]} {at:%H:%M}"
    if upcoming.step is StepName.NUDGE:
        return f"{text} ({ONLY_IF_UNCONFIRMED.format(emoji=config.emoji)})"
    return text


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
