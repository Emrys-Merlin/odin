"""The weekly cycle as a reconcile loop.

`reconcile` looks at (config, state, now) and does whatever is due and not yet recorded for the
current dinner week, in schedule order:

1. **flat ask** — ask the flat group; its reactions are the confirmations.
2. **nudge** (optional) — remind the flat group, only if nobody has confirmed yet.
3. **decision** at the flat deadline — announcement (≥1 confirmation) or cancellation (none) to
   the dinner group.
4. **tally** — only if dinner is on: how many reacted to the announcement.

Every step ends up recorded exactly once per week, as sent or as skipped (too late, or not needed),
so nothing is ever sent twice and a restart picks up where the last run stopped. A step is only
recorded after its message went out; a failed send leaves it unrecorded and stops the tick, so the
next tick retries it and later steps never overtake it.

**Sending is at least once.** A send counts as failed only if Signal did not accept it: an HTTP
error, no connection, or a timeout. A send that Signal accepted but whose response cannot be read
(no timestamp) is recorded as sent — it was posted. Its message cannot be tracked then, so the
reactions to it are not counted (an untracked flat poll has no confirmations, so the week is
cancelled); that is logged as an error. A timeout while waiting for the response is the one case
in which a message may be posted twice: it is retried, because a message that never went out —
most of all the cancellation — is worse than a duplicate. The send timeout is long (see
`odin.signal.rest`), so this stays rare.

**Catch-up:** a step that is due is still performed while within its window: from its scheduled
time until the catch-up grace has passed, but never after its expiry — the flat deadline for the
flat ask and the nudge (after it, confirmations no longer count), dinner start for the decision
and the tally. A step past its window is recorded as skipped. Without a flat ask nobody can confirm,
so a skipped flat ask skips the rest of the week, including the dinner-group message.

**A new dinner weekday** (see `transition`) makes the dinner weeks named by another weekday. The
change never takes over in the middle of a running week; the first week under the new weekday
either starts cleanly after the switch, or all of its steps lie before the switch and it is
**dropped**. Whoever applies the switch records a dropped week in the store (`record_transition`),
so the engine knows it from state. A dropped week runs like a week whose flat ask was missed —
its flat ask, nudge and tally are recorded as skipped — except that the dinner group still gets
the cancellation: it is due from the switch (see `dropped_cancellation_window`), so it goes out on
the first tick after the switch, and is skipped like any late step after the dropped week's dinner
start or once the catch-up grace counted from the switch has passed.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from odin.config import Config, WeeklyTime
from odin.reactions import count_confirmations
from odin.signal import SendResponseUnreadable, SignalClient
from odin.store import Action, MessageKind, Outcome, Store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Account:
    """Where the bot sends to, and who it is (the author of the messages it tracks)."""

    number: str
    flat_group_id: str
    dinner_group_id: str


@dataclass(frozen=True)
class Step:
    """An action recorded during a tick."""

    week: date
    action: Action
    outcome: Outcome


def dinner_week(config: Config, now: datetime) -> date:
    """The dinner week `now` belongs to, identified by its dinner date.

    A week runs until its dinner starts; from then on it is the next week.
    """
    now = _utc(now)
    local = now.astimezone(config.timezone)
    dinner = config.schedule.dinner
    week = local.date() + timedelta(days=(dinner.weekday - local.weekday()) % 7)
    if now >= config.when(dinner, week).astimezone(UTC):
        week += timedelta(weeks=1)
    return week


@dataclass(frozen=True)
class Upcoming:
    """A scheduled action and when it happens next."""

    name: str
    at: datetime
    note: str = ""


def upcoming_actions(config: Config, now: datetime) -> list[Upcoming]:
    """The next occurrence of each scheduled action at or after `now`, in time order.

    Schedule only: whether an action is actually sent depends on the state at that time.
    """
    s = config.schedule
    points: list[tuple[str, WeeklyTime, str]] = [
        ("flat ask", s.flat_ask, "flat group"),
    ]
    if s.nudge is not None:
        points.append(("nudge", s.nudge, "flat group, only if nobody confirmed"))
    points += [
        ("announcement / cancellation", s.flat_deadline, "dinner group"),
        ("tally", s.tally, "flat group, only if dinner is on"),
    ]
    week = dinner_week(config, now)
    upcoming = []
    for name, point, note in points:
        at = config.when(point, week)
        if at < now:
            at = config.when(point, week + timedelta(weeks=1))
        upcoming.append(Upcoming(name, at, note))
    return sorted(upcoming, key=lambda u: u.at.astimezone(UTC))


@dataclass(frozen=True)
class StepWindow:
    """When a step of a dinner week is due: from `start` until before `end` (both UTC).

    `end` is the step's expiry, cut short by the catch-up grace if one is configured.
    """

    name: str  # "flat_ask", "nudge", "decision", "tally"
    actions: tuple[Action, ...]  # the step is done once any of these is recorded
    start: datetime
    end: datetime

    def due(self, now: datetime) -> bool | None:
        """None: not yet due. True: due and within its window. False: past its window."""
        if now < self.start:
            return None
        return now < self.end


def _window(
    config: Config, name: str, actions: tuple[Action, ...], start: datetime, expiry: datetime
) -> StepWindow:
    end = expiry
    if config.catch_up_grace is not None:
        end = min(end, start + config.catch_up_grace)
    return StepWindow(name, actions, start, end)


def step_windows(config: Config, week: date) -> list[StepWindow]:
    """The steps of dinner week `week` in schedule order, with when each is due.

    The nudge is left out while it is disabled. For a dropped week, the cancellation is due as
    `dropped_cancellation_window` says instead.
    """
    schedule = config.schedule

    def at(point: WeeklyTime) -> datetime:
        return config.when(point, week).astimezone(UTC)

    def window(
        name: str, actions: tuple[Action, ...], start: datetime, expiry: datetime
    ) -> StepWindow:
        return _window(config, name, actions, start, expiry)

    deadline, dinner = at(schedule.flat_deadline), at(schedule.dinner)
    windows = [window("flat_ask", (Action.FLAT_ASK,), at(schedule.flat_ask), deadline)]
    if schedule.nudge is not None:
        windows.append(window("nudge", (Action.NUDGE,), at(schedule.nudge), deadline))
    windows.append(window("decision", (Action.ANNOUNCEMENT, Action.CANCELLATION), deadline, dinner))
    windows.append(window("tally", (Action.TALLY,), at(schedule.tally), dinner))
    return windows


def dropped_cancellation_window(config: Config, week: date, switch: datetime) -> StepWindow:
    """When the cancellation of dropped week `week` is due: from the `switch` that dropped it
    until the week's dinner starts, cut short by the catch-up grace counted from the switch."""
    dinner = config.when(config.schedule.dinner, week).astimezone(UTC)
    return _window(config, "decision", (Action.CANCELLATION,), _utc(switch), dinner)


@dataclass(frozen=True)
class Transition:
    """How the dinner weeks of a new schedule begin when it takes over at a given moment."""

    switch: datetime  # when the new schedule takes over (UTC)
    first_week: date  # the first dinner week that is run under the new schedule
    dropped_week: date | None  # the week before it, if all its steps lie before the switch


def transition(new: Config, switch: datetime) -> Transition:
    """How the weeks of `new` begin when `new` becomes the effective config at `switch`.

    Takes the first week of `new` whose dinner is after `switch`. If all its steps start after
    the switch, it is run normally. If all of them start at or before it, it is dropped: the
    engine records its flat ask, nudge and tally as skipped (they are past their windows), posts
    only the cancellation, and the next week is the first one run. The engine only knows a week
    is dropped once `record_transition` stored it, at the moment the switch is applied. A week
    whose steps lie on both sides of the switch would be half-run; raises ValueError then.

    When `switch` is a dinner of the old schedule and both schedules are in order (see
    `odin.config`), that cannot happen: before the old dinner its steps run flat ask … tally in
    that order, so the new week's steps before the switch are the *last* ones of that order;
    within the new week they would have to be the *first* ones — so it is all of them or none.
    """
    switch = _utc(switch)
    week = dinner_week(new, switch)
    starts = [window.start for window in step_windows(new, week)]
    if all(start > switch for start in starts):
        return Transition(switch, week, None)
    if all(start <= switch for start in starts):
        return Transition(switch, week + timedelta(weeks=1), week)
    raise ValueError(f"the dinner week {week} would start before {switch} and end after it")


def record_transition(store: Store, weeks: Transition) -> None:
    """Store what the engine has to know about a new dinner weekday taking over.

    Call it when the new schedule becomes the effective one (at `weeks.switch`), in the same
    transaction as the change itself, so that a restart never loses it. It records the dropped
    week, if any, with the switch: `reconcile` then posts that week's cancellation once. A week
    that a later switch runs normally (`first_week`) is no longer dropped.
    """
    store.delete_dropped_week(weeks.first_week)
    if weeks.dropped_week is not None:
        store.record_dropped_week(weeks.dropped_week, weeks.switch)


async def reconcile(
    config: Config, store: Store, client: SignalClient, account: Account, now: datetime
) -> list[Step]:
    """Perform what is due by `now` and not yet recorded. Returns what was recorded.

    Also finishes the earlier weeks, oldest first, so that a step missed there (the bot was down
    over dinner) is recorded as skipped instead of staying open forever: every week before
    `current` that was started or dropped but is not finished yet (see
    `Store.unfinished_weeks_before`) — after a new dinner weekday took over, that can be weeks of
    both weekdays, e.g. the last old week and a dropped one — and the week before `current`,
    even if nothing of it was recorded. Right after a new dinner weekday took over, a week is
    recorded after that one, so it never existed and is left alone.
    """
    now = _utc(now)
    current = dinner_week(config, now)
    earlier = set(store.unfinished_weeks_before(current))
    previous = current - timedelta(weeks=1)
    latest = store.latest_week_before(current)
    if latest is None or latest <= previous:
        earlier.add(previous)
    steps: list[Step] = []
    weeks = [(week, True) for week in sorted(earlier)] + [(current, False)]
    for week, over in weeks:
        cycle = _Week(config, store, client, account, week, over, now, steps)
        try:
            await cycle.run()
        except _SendFailed:
            break
    return steps


class _SendFailed(Exception):
    pass


@dataclass
class _Week:
    config: Config
    store: Store
    client: SignalClient
    account: Account
    week: date
    # The week's dinner has started: every step still open is past its window. Its windows are
    # not computed, since the week may belong to an earlier dinner weekday.
    over: bool
    now: datetime
    steps: list[Step] = field(default_factory=list)

    async def run(self) -> None:
        windows = {} if self.over else {w.name: w for w in step_windows(self.config, self.week)}

        def due(name: str) -> bool | None:
            return False if self.over else windows[name].due(self.now)

        # 1. Flat ask.
        if not self._recorded(Action.FLAT_ASK):
            due_now = due("flat_ask")
            if due_now is None:
                return
            if due_now:
                await self._send(Action.FLAT_ASK, track=MessageKind.FLAT_POLL)
            else:
                self._skip(Action.FLAT_ASK)
        asked = self.store.action_outcome(self.week, Action.FLAT_ASK) is Outcome.SENT

        # 2. Nudge, if enabled.
        if self.config.schedule.nudge is not None and not self._recorded(Action.NUDGE):
            due_now = due("nudge")
            if due_now is None:
                return
            if due_now and asked and self._confirmations() == 0:
                await self._send(Action.NUDGE)
            else:
                self._skip(Action.NUDGE)

        # 3. Decision: announcement or cancellation. A dropped week was never asked; it gets the
        # cancellation, due from the switch that dropped it.
        if not (self._recorded(Action.ANNOUNCEMENT) or self._recorded(Action.CANCELLATION)):
            dropped = None if asked or self.over else self.store.dropped_at(self.week)
            if dropped is not None:
                due_now = dropped_cancellation_window(self.config, self.week, dropped).due(self.now)
            else:
                due_now = due("decision")
            if due_now is None:
                return
            on = asked and self._confirmations() > 0
            decision = Action.ANNOUNCEMENT if on else Action.CANCELLATION
            if due_now and (asked or dropped is not None):
                track = MessageKind.DINNER_ANNOUNCEMENT if on else None
                await self._send(decision, track=track)
            else:
                self._skip(decision)
        on = self.store.action_outcome(self.week, Action.ANNOUNCEMENT) is Outcome.SENT

        # 4. Tally, if dinner is on.
        if not self._recorded(Action.TALLY):
            due_now = due("tally")
            if due_now is None:
                return
            if due_now and on:
                announcement = self.store.tracked_message(
                    self.week, MessageKind.DINNER_ANNOUNCEMENT
                )
                count = (
                    0
                    if announcement is None
                    else count_confirmations(self.store, announcement, self.config.emoji)
                )
                await self._send(Action.TALLY, count=count)
            else:
                self._skip(Action.TALLY)

    def _recorded(self, action: Action) -> bool:
        return self.store.has_action(self.week, action)

    def _confirmations(self) -> int:
        poll = self.store.tracked_message(self.week, MessageKind.FLAT_POLL)
        if poll is None:
            return 0
        return count_confirmations(self.store, poll, self.config.emoji)

    async def _send(
        self, action: Action, *, track: MessageKind | None = None, **values: object
    ) -> None:
        to_dinner = action in (Action.ANNOUNCEMENT, Action.CANCELLATION)
        group = self.account.dinner_group_id if to_dinner else self.account.flat_group_id
        template = getattr(self.config.templates, action.value)
        text = template.render(**self.config.placeholder_values(), **values)
        timestamp: int | None
        try:
            timestamp = await self.client.send_group_message(group, text)
        except SendResponseUnreadable as e:
            timestamp = None
            if track is None:
                logger.warning("sent %s for week %s, but %s", action, self.week, e)
            else:
                logger.error(
                    "sent %s for week %s, but %s; its reactions cannot be counted",
                    action,
                    self.week,
                    e,
                )
        except Exception:
            logger.exception("sending %s for week %s failed; retrying next tick", action, self.week)
            raise _SendFailed from None
        with self.store.transaction():
            self.store.record_action(self.week, action, self.now)
            if track is not None and timestamp is not None:
                self.store.track_message(self.week, track, group, self.account.number, timestamp)
        logger.info("sent %s for week %s", action, self.week)
        self.steps.append(Step(self.week, action, Outcome.SENT))

    def _skip(self, action: Action) -> None:
        self.store.record_action(self.week, action, self.now, Outcome.SKIPPED)
        logger.info("skipped %s for week %s", action, self.week)
        self.steps.append(Step(self.week, action, Outcome.SKIPPED))


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"naive datetime not allowed: {moment!r}")
    return moment.astimezone(UTC)
