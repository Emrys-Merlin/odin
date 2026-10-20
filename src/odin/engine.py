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
reactions to it are not counted; that is logged as an error, and the flat group is told once (see
`odin.notices`), right after the step, as an action of its own:

- an untracked **flat poll** is asked again (`FLAT_ASK_RETRY`): the new message is tracked as the
  week's flat poll, so the nudge and the decision count the reactions on it. It is due until the
  flat deadline; if it is not out by then (or its response is unreadable too), the reactions
  count as none, so the week is cancelled.
- an untracked **announcement** gets a notice (`ANNOUNCEMENT_NOTICE`) that the tally will show 0,
  due until dinner starts.

A notice whose send fails is retried on the next tick, but never holds up the steps after it.
A timeout while waiting for the response is the one case
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
start or once the catch-up grace counted from the switch has passed. Its text is the
`weekday_change_cancellation` template (which falls back to `cancellation` while it is not set);
it is recorded as the week's cancellation like any other.

**Cancelled via chat** (`/cancel`, see `odin.commands.cancel`): ODIN's reply to `/cancel` is
tracked as the week's cancel request. Once anyone reacts to it with the configured emoji, the next
tick posts the cancellation to the dinner group, whatever the week's state, as long as the week's
dinner has not started (an earlier, finished week never acts on it) and no cancellation is
recorded yet: before the decision it *is* the decision, after an announcement it follows it. From
then on dinner is off: an open flat ask or nudge is skipped at once (the week needs no
confirmations any more), and the tally is skipped at its time, as after any cancellation.

**A skip date** (`/skip`, see `odin.commands.skip`) is a dinner week set in advance to have no
dinner. It runs like a week whose flat ask was missed — the flat ask, nudge and tally are recorded
as skipped, each at its time, so `/unskip` works until the flat ask is due — except that the
dinner group still gets the cancellation at the usual decision time. A skip date only counts while
the week's flat ask has not gone out; after that, skipping the week is `/cancel`.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from odin import notices
from odin.config import Config, WeeklyTime, dropped_placeholder_values
from odin.cycle import StepName
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


@dataclass(frozen=True)
class SendFailure:
    """A send that failed during a tick; the action stays unrecorded, so it is retried."""

    week: date
    action: Action
    error: str  # the exception's class name: no message, it may hold personal data


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

    step: StepName
    at: datetime
    week: date  # the dinner week the action belongs to
    note: str = ""


def upcoming_actions(config: Config, now: datetime) -> list[Upcoming]:
    """The next occurrence of each scheduled action at or after `now`, in time order.

    Schedule only: whether an action is actually sent depends on the state at that time.
    """
    s = config.schedule
    points: list[tuple[StepName, WeeklyTime, str]] = [
        (StepName.FLAT_ASK, s.flat_ask, "flat group"),
    ]
    if s.nudge is not None:
        points.append((StepName.NUDGE, s.nudge, "flat group, only if nobody confirmed"))
    points += [
        (StepName.DECISION, s.flat_deadline, "dinner group"),
        (StepName.TALLY, s.tally, "flat group, only if dinner is on"),
    ]
    week = dinner_week(config, now)
    upcoming = []
    for step, point, note in points:
        of, at = week, config.when(point, week)
        if at < now:
            of = week + timedelta(weeks=1)
            at = config.when(point, of)
        upcoming.append(Upcoming(step, at, of, note))
    return sorted(upcoming, key=lambda u: u.at.astimezone(UTC))


@dataclass(frozen=True)
class StepWindow:
    """When a step of a dinner week is due: from `start` until before `end` (both UTC).

    `end` is the step's expiry, cut short by the catch-up grace if one is configured.
    """

    name: StepName
    actions: tuple[Action, ...]  # the step is done once any of these is recorded
    start: datetime
    end: datetime

    def due(self, now: datetime) -> bool | None:
        """None: not yet due. True: due and within its window. False: past its window."""
        if now < self.start:
            return None
        return now < self.end


def _window(
    config: Config, name: StepName, actions: tuple[Action, ...], start: datetime, expiry: datetime
) -> StepWindow:
    return StepWindow(name, actions, start, _grace_end(config, start, expiry))


def _grace_end(config: Config, start: datetime, expiry: datetime) -> datetime:
    """`expiry`, cut short by the catch-up grace counted from `start`."""
    if config.catch_up_grace is not None:
        return min(expiry, start + config.catch_up_grace)
    return expiry


def step_windows(config: Config, week: date) -> list[StepWindow]:
    """The steps of dinner week `week` in schedule order, with when each is due.

    The nudge is left out while it is disabled. For a dropped week, the cancellation is due as
    `dropped_cancellation_window` says instead.
    """
    schedule = config.schedule

    def at(point: WeeklyTime) -> datetime:
        return config.when(point, week).astimezone(UTC)

    def window(
        name: StepName, actions: tuple[Action, ...], start: datetime, expiry: datetime
    ) -> StepWindow:
        return _window(config, name, actions, start, expiry)

    deadline, dinner = at(schedule.flat_deadline), at(schedule.dinner)
    windows = [window(StepName.FLAT_ASK, (Action.FLAT_ASK,), at(schedule.flat_ask), deadline)]
    if schedule.nudge is not None:
        windows.append(window(StepName.NUDGE, (Action.NUDGE,), at(schedule.nudge), deadline))
    windows.append(
        window(StepName.DECISION, (Action.ANNOUNCEMENT, Action.CANCELLATION), deadline, dinner)
    )
    windows.append(window(StepName.TALLY, (Action.TALLY,), at(schedule.tally), dinner))
    return windows


def dropped_cancellation_window(config: Config, week: date, switch: datetime) -> StepWindow:
    """When the cancellation of dropped week `week` is due: from the `switch` that dropped it
    until the week's dinner starts, cut short by the catch-up grace counted from the switch."""
    dinner = config.when(config.schedule.dinner, week).astimezone(UTC)
    return _window(config, StepName.DECISION, (Action.CANCELLATION,), _utc(switch), dinner)


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
    config: Config,
    store: Store,
    client: SignalClient,
    account: Account,
    now: datetime,
    failures: list[SendFailure] | None = None,
) -> list[Step]:
    """Perform what is due by `now` and not yet recorded. Returns what was recorded; the sends
    that failed are appended to `failures`, if given (see `odin.health`).

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
    failures = [] if failures is None else failures
    weeks = [(week, True) for week in sorted(earlier)] + [(current, False)]
    for week, over in weeks:
        cycle = _Week(config, store, client, account, week, over, now, steps, failures)
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
    failures: list[SendFailure] = field(default_factory=list)
    # Set during `run`, by the step that decides them; later steps read them.
    _windows: dict[StepName, StepWindow] = field(init=False, default_factory=dict)
    _cancelled: bool = field(init=False, default=False)  # the cancellation went out
    _skip_date: bool = field(init=False, default=False)
    _asked: bool = field(init=False, default=False)  # the flat ask went out
    _on: bool = field(init=False, default=False)  # dinner is on: announced and not cancelled

    async def run(self) -> None:
        """Run the week's steps in schedule order.

        Each step returns whether the run goes on: False means the step is not due yet, so
        neither it nor any later step is done this tick.
        """
        if not self.over:
            self._windows = {w.name: w for w in step_windows(self.config, self.week)}
        await self._cancel()
        for step in (self._flat_ask, self._nudge, self._decide, self._tally):
            if not await step():
                return

    def _due(self, name: StepName) -> bool | None:
        return False if self.over else self._windows[name].due(self.now)

    async def _cancel(self) -> None:
        """0. Cancellation via /cancel, once confirmed: it overtakes every other step."""
        if not self.over and not self._recorded(Action.CANCELLATION) and self._cancel_confirmed():
            await self._send(Action.CANCELLATION)
        self._cancelled = self.store.action_outcome(self.week, Action.CANCELLATION) is Outcome.SENT
        self._skip_date = not self.over and self.store.skip_date(self.week) is not None

    async def _flat_ask(self) -> bool:
        """1. Flat ask; not asked on a skip date, but only skipped at its time (until then /unskip
        can take the skip date back)."""
        if not self._recorded(Action.FLAT_ASK):
            due_now = False if self._cancelled else self._due(StepName.FLAT_ASK)
            if due_now is None:
                return False
            if due_now and not self._skip_date:
                await self._send(Action.FLAT_ASK, track=MessageKind.FLAT_POLL)
            else:
                self._skip(Action.FLAT_ASK)
        self._asked = self.store.action_outcome(self.week, Action.FLAT_ASK) is Outcome.SENT
        if self._asked and not self._cancelled:  # a cancelled week needs no confirmations
            await self._notify_untracked(
                Action.FLAT_ASK,
                MessageKind.FLAT_POLL,
                Action.FLAT_ASK_RETRY,
                self.config.schedule.flat_deadline,
            )
        return True

    async def _nudge(self) -> bool:
        """2. Nudge, if enabled."""
        if self.config.schedule.nudge is None or self._recorded(Action.NUDGE):
            return True
        due_now = False if self._cancelled else self._due(StepName.NUDGE)
        if due_now is None:
            return False
        if due_now and self._asked and self._confirmations() == 0:
            await self._send(Action.NUDGE)
        else:
            self._skip(Action.NUDGE)
        return True

    async def _decide(self) -> bool:
        """3. Decision: announcement or cancellation. A dropped week was never asked; it gets the
        cancellation, due from the switch that dropped it. A skip date was not asked either; it
        gets the cancellation at the usual time."""
        if not (self._recorded(Action.ANNOUNCEMENT) or self._recorded(Action.CANCELLATION)):
            dropped = None if self._asked or self.over else self.store.dropped_at(self.week)
            skipped = self._skip_date and not self._asked
            if dropped is not None:
                due_now = dropped_cancellation_window(self.config, self.week, dropped).due(self.now)
            else:
                due_now = self._due(StepName.DECISION)
            if due_now is None:
                return False
            on = self._asked and self._confirmations() > 0
            decision = Action.ANNOUNCEMENT if on else Action.CANCELLATION
            if due_now and dropped is not None:
                dates = dropped_placeholder_values(self.week)
                await self._send(
                    decision,
                    template="weekday_change_cancellation",
                    dropped_date=dates["dropped_date"],
                    first_date=dates["first_date"],
                )
            elif due_now and (self._asked or skipped):
                track = MessageKind.DINNER_ANNOUNCEMENT if on else None
                await self._send(decision, track=track)
            else:
                self._skip(decision)
        announced = self.store.action_outcome(self.week, Action.ANNOUNCEMENT) is Outcome.SENT
        self._on = announced and not self._cancelled
        if self._on:
            await self._notify_untracked(
                Action.ANNOUNCEMENT,
                MessageKind.DINNER_ANNOUNCEMENT,
                Action.ANNOUNCEMENT_NOTICE,
                self.config.schedule.dinner,
            )
        return True

    async def _tally(self) -> bool:
        """4. Tally, if dinner is on."""
        if self._recorded(Action.TALLY):
            return True
        due_now = self._due(StepName.TALLY)
        if due_now is None:
            return False
        if due_now and self._on:
            announcement = self.store.tracked_message(self.week, MessageKind.DINNER_ANNOUNCEMENT)
            count = (
                0
                if announcement is None
                else count_confirmations(self.store, announcement, self.config.emoji)
            )
            await self._send(Action.TALLY, count=count)
        else:
            self._skip(Action.TALLY)
        return True

    def _recorded(self, action: Action) -> bool:
        return self.store.has_action(self.week, action)

    def _cancel_confirmed(self) -> bool:
        request = self.store.tracked_message(self.week, MessageKind.CANCEL_REQUEST)
        if request is None:
            return False
        return count_confirmations(self.store, request, self.config.emoji) > 0

    def _confirmations(self) -> int:
        poll = self.store.tracked_message(self.week, MessageKind.FLAT_POLL)
        if poll is None:
            return 0
        return count_confirmations(self.store, poll, self.config.emoji)

    async def _send(
        self,
        action: Action,
        *,
        track: MessageKind | None = None,
        template: str | None = None,
        **values: object,
    ) -> None:
        """Post `action` with its template, or with the template named `template` instead."""
        to_dinner = action in (Action.ANNOUNCEMENT, Action.CANCELLATION)
        group = self.account.dinner_group_id if to_dinner else self.account.flat_group_id
        text = self.config.templates.get(template or action.value).render(
            **self.config.placeholder_values(), **values
        )
        if not await self._post(action, group, text, track):
            raise _SendFailed

    async def _notify_untracked(
        self, sent: Action, kind: MessageKind, notice: Action, expiry: WeeklyTime
    ) -> None:
        """Tell the flat group, once, that `sent` went out but its message is not tracked.

        Due from when `sent` was recorded until `expiry` of this week, cut short by the catch-up
        grace. A failed notice is retried next tick, but never holds up the weekly steps after it.
        """
        if self.store.tracked_message(self.week, kind) is not None or self._recorded(notice):
            return
        due_now: bool | None = False
        if not self.over:
            start = self.store.action_time(self.week, sent)
            assert start is not None
            end = _grace_end(
                self.config, start, self.config.when(expiry, self.week).astimezone(UTC)
            )
            due_now = None if self.now < start else self.now < end
        if due_now is None:
            return
        if not due_now:
            self._skip(notice)
            return
        # The retry is the week's flat poll from now on; the announcement stays untracked.
        if notice is Action.FLAT_ASK_RETRY:
            text, track = notices.FLAT_ASK_RETRY, MessageKind.FLAT_POLL
        else:
            text, track = notices.ANNOUNCEMENT_NOTICE, None
        group = self.account.flat_group_id
        await self._post(notice, group, notices.render(text, self.config), track)

    async def _post(self, action: Action, group: str, text: str, track: MessageKind | None) -> bool:
        """Send `text` and record `action` as sent. Returns False if the send failed; nothing
        is recorded then."""
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
        except Exception as e:
            logger.exception("sending %s for week %s failed; retrying next tick", action, self.week)
            self.failures.append(SendFailure(self.week, action, type(e).__name__))
            return False
        with self.store.transaction():
            self.store.record_action(self.week, action, self.now)
            if track is not None and timestamp is not None:
                self.store.track_message(self.week, track, group, self.account.number, timestamp)
        logger.info("sent %s for week %s", action, self.week)
        self.steps.append(Step(self.week, action, Outcome.SENT))
        return True

    def _skip(self, action: Action) -> None:
        self.store.record_action(self.week, action, self.now, Outcome.SKIPPED)
        logger.info("skipped %s for week %s", action, self.week)
        self.steps.append(Step(self.week, action, Outcome.SKIPPED))


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"naive datetime not allowed: {moment!r}")
    return moment.astimezone(UTC)
