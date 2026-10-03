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

**Catch-up:** a step that is due is still performed while within its window: from its scheduled
time until the catch-up grace has passed, but never after its expiry — the flat deadline for the
flat ask and the nudge (after it, confirmations no longer count), dinner start for the decision
and the tally. A step past its window is recorded as skipped. Without a flat ask nobody can confirm,
so a skipped flat ask skips the rest of the week, including the dinner-group message.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from odib.config import Config, WeeklyTime
from odib.reactions import count_confirmations
from odib.signal import SignalClient
from odib.store import Action, MessageKind, Outcome, Store

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


async def reconcile(
    config: Config, store: Store, client: SignalClient, account: Account, now: datetime
) -> list[Step]:
    """Perform what is due by `now` and not yet recorded. Returns what was recorded.

    Also finishes the previous week, so that a step missed there (the bot was down over dinner)
    is recorded as skipped instead of staying open forever.
    """
    now = _utc(now)
    current = dinner_week(config, now)
    steps: list[Step] = []
    for week in (current - timedelta(weeks=1), current):
        cycle = _Week(config, store, client, account, week, now, steps)
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
    now: datetime
    steps: list[Step] = field(default_factory=list)

    async def run(self) -> None:
        schedule = self.config.schedule
        deadline = self._at(schedule.flat_deadline)
        dinner = self._at(schedule.dinner)

        # 1. Flat ask.
        if not self._recorded(Action.FLAT_ASK):
            due = self._due(self._at(schedule.flat_ask), deadline)
            if due is None:
                return
            if due:
                await self._send(Action.FLAT_ASK, track=MessageKind.FLAT_POLL)
            else:
                self._skip(Action.FLAT_ASK)
        asked = self.store.action_outcome(self.week, Action.FLAT_ASK) is Outcome.SENT

        # 2. Nudge, if enabled.
        if schedule.nudge is not None and not self._recorded(Action.NUDGE):
            due = self._due(self._at(schedule.nudge), deadline)
            if due is None:
                return
            if due and asked and self._confirmations() == 0:
                await self._send(Action.NUDGE)
            else:
                self._skip(Action.NUDGE)

        # 3. Decision: announcement or cancellation.
        if not (self._recorded(Action.ANNOUNCEMENT) or self._recorded(Action.CANCELLATION)):
            due = self._due(deadline, dinner)
            if due is None:
                return
            on = asked and self._confirmations() > 0
            decision = Action.ANNOUNCEMENT if on else Action.CANCELLATION
            if due and asked:
                track = MessageKind.DINNER_ANNOUNCEMENT if on else None
                await self._send(decision, track=track)
            else:
                self._skip(decision)
        on = self.store.action_outcome(self.week, Action.ANNOUNCEMENT) is Outcome.SENT

        # 4. Tally, if dinner is on.
        if not self._recorded(Action.TALLY):
            due = self._due(self._at(schedule.tally), dinner)
            if due is None:
                return
            if due and on:
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

    def _at(self, point: WeeklyTime) -> datetime:
        return self.config.when(point, self.week).astimezone(UTC)

    def _due(self, start: datetime, expiry: datetime) -> bool | None:
        """None: not yet due. True: due and within its window. False: past its window."""
        if self.now < start:
            return None
        end = expiry
        if self.config.catch_up_grace is not None:
            end = min(end, start + self.config.catch_up_grace)
        return self.now < end

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
        try:
            timestamp = await self.client.send_group_message(group, text)
        except Exception:
            logger.exception("sending %s for week %s failed; retrying next tick", action, self.week)
            raise _SendFailed from None
        with self.store.transaction():
            self.store.record_action(self.week, action, self.now)
            if track is not None:
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
