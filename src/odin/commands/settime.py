"""/settime, /nudge and /resettime: move the points of the weekly schedule from the chat.

A change takes effect at once, but it is guarded: it is rejected (and nothing is stored) if it
breaks the order of the schedule, moves the current dinner week, or makes a step of the current
week that has not happened yet due right now. See `check_change`.

A new dinner weekday is the exception (see `set_dinner_day`): it never touches the running dinner
week. Once that week has started (its flat ask is due or anything of it is recorded), the change
waits until the week's dinner; before that, it applies at once. A week of the new weekday whose
steps would all lie before the switch is dropped: ODIN posts only its cancellation, and the reply
says so.
"""

import re
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta

from odin.commands import ui
from odin.commands.core import Command, CommandContext, CommandError
from odin.config import WEEKDAYS_DE, WEEKDAYS_EN, Config, ConfigError, WeeklyTime
from odin.engine import dinner_week, record_transition, step_windows, transition
from odin.overrides import (
    DINNER_KEY,
    EDITABLE_TEMPLATES,
    NUDGE_ENABLED_KEY,
    PENDING_DINNER_KEY,
    SCHEDULE_POINTS,
    PendingDinner,
    apply_overrides,
    current_values,
    format_bool,
    format_weekly_time,
    pending_dinner,
    schedule_key,
)
from odin.store import Action, Outcome

# --- German UI strings --------------------------------------------------------------------------

# What each schedule point is, for replies.
POINT_LABELS = {
    "flat_ask": "Frage an die WG",
    "nudge": "Erinnerung an die WG",
    "flat_deadline": "Frist für die WG / Entscheidung",
    "rsvp_by": "Rückmeldung der Gäste bis",
    "tally": "Zählung der Gäste",
    "cook": "Kochen",
    "dinner": "Essen",
}
# The steps of the weekly cycle (see `odin.engine.step_windows`), for the guard's message.
STEP_LABELS = {
    "flat_ask": "die Frage an die WG",
    "nudge": "die Erinnerung",
    "decision": "die Entscheidung",
    "tally": "die Zählung",
}

POINT_LIST = ", ".join(SCHEDULE_POINTS)
SETTIME_USAGE = (
    "So geht's: /settime <punkt> <tag> <HH:MM>, z. B. /settime flat_deadline thu 12:00.\n"
    f"Punkte: {POINT_LIST}"
)
RESETTIME_USAGE = f"So geht's: /resettime <punkt>, z. B. /resettime tally.\nPunkte: {POINT_LIST}"
NUDGE_USAGE = "So geht's: /nudge on oder /nudge off."
UNKNOWN_POINT = "Den Zeitpunkt {point} kenne ich nicht. Punkte: " + POINT_LIST
UNKNOWN_WEEKDAY = "Den Wochentag {day} kenne ich nicht – nimm z. B. mon, tue, … oder monday, …"
BAD_TIME = "Die Uhrzeit {time} verstehe ich nicht – bitte als HH:MM, z. B. 18:00."

ORDER_RULE = (
    "Die Zeitpunkte müssen in der Woche bis zum Essen in dieser Reihenfolge liegen: "
    "flat_ask → nudge → flat_deadline → tally → dinner; rsvp_by und cook nach flat_deadline "
    "(rsvp_by darf gleich sein)."
)
ORDER_BROKEN = "Das passt nicht: {first} muss vor {second} liegen. " + ORDER_RULE
ORDER_BROKEN_GENERIC = "Das passt nicht in den Wochenplan. " + ORDER_RULE
# The prefix when a change does not fit the schedule under a pending new dinner weekday.
WITH_NEW_DINNER = "Mit dem neuen Essenstag ({when}, ab {first}): "
WEEK_MOVES = (
    "Damit würde sich die aktuelle Essenswoche verschieben (Essen am {old} → {new}) – "
    "das geht nicht über den Chat."
)
# Should not happen (see `odin.engine.transition`); refused rather than half-running a week.
DINNER_DAY_UNSAFE = (
    "Dieser Wechsel des Essenstags würde eine Essenswoche mittendrin abschneiden – "
    "das geht nicht über den Chat."
)
STEP_DUE = "Dann wäre {step} sofort fällig – das geht nicht über den Chat."

SAVED = "Gespeichert ✅"
RESET = "Zurückgesetzt ✅ (wieder wie in der Config)"
NOT_OVERRIDDEN = "{label} ({point}) war nicht geändert – steht auf {when}."
NUDGE_NOT_OVERRIDDEN = "Die Erinnerung war nicht geändert – sie ist {state}, {when}."
POINT_LINE = "{label} ({point}): {when}, nächstes Mal {next}"
NUDGE_OFF_LINE = "Erinnerung an die WG (nudge): aus"
NUDGE_OFF_NOTE = "Die Erinnerung ist ausgeschaltet; die Zeit gilt, wenn sie wieder an ist."
THIS_WEEK = "Das gilt schon für diese Woche."
FROM_NEXT_WEEK = "Das gilt ab nächster Woche."
ASK_ALREADY_SENT = (
    "Achtung: Die Frage an die WG ist diese Woche schon raus und nennt noch die alte Frist "
    "({old}). Sag am besten in der Gruppe Bescheid, dass jetzt {new} gilt."
)
ANNOUNCEMENT_ALREADY_SENT = (
    "Achtung: Die Ankündigung ist diese Woche schon raus und nennt noch die alte Zeit für "
    "{point} ({old}). Sag am besten in der Essensgruppe Bescheid, dass jetzt {new} gilt."
)
DINNER_MOVED = "Essen (dinner): {old} → {new}"
DINNER_FROM_NEXT = "Das gilt ab dem Essen am {first}. Diese Woche bleibt es beim Essen am {this}."
DINNER_FROM_NOW = "Das gilt schon ab dieser Woche: nächstes Essen am {first}."
DINNER_WEEK_DROPPED = (
    "Achtung: Am {day} gibt es kein Essen – diese Woche fällt beim Wechsel aus, weil ihre Frage "
    "an die WG schon vor dem Wechsel dran gewesen wäre."
)
DROPPED_CANCELLATION_LATER = (
    "Die Absage für den {day} schicke ich der Essensgruppe beim Wechsel ({switch})."
)
DROPPED_CANCELLATION_NOW = "Die Absage für den {day} schicke ich der Essensgruppe gleich."
PENDING_DISCARDED = "Der geplante Wechsel auf {new} (ab {first}) ist damit verworfen."
PENDING_CANCELLED = "Verworfen ✅ Der geplante Wechsel auf {new} (ab {first}) fällt weg."
HARDCODED_WEEKDAY = (
    "Achtung: Die Vorlage {name} nennt einen Wochentag fest – prüfe sie mit /text {name}."
)

# --- Parsing ------------------------------------------------------------------------------------

# Accepted weekday spellings → 0 = Monday … 6 = Sunday: what the config accepts (mon, monday).
# Commands and their arguments are English only, like the command names.
WEEKDAY_NAMES: dict[str, int] = {
    name.lower(): i for i, en in enumerate(WEEKDAYS_EN) for name in (en, en[:3])
}

_TIME = re.compile(r"(\d{1,2}):(\d{2})")
_ON = {"on": True, "off": False}
_ORDER_ERROR = re.compile(r"schedule: (\w+) \(.*\) must come before (\w+) ")
_HARDCODED_DAY = re.compile(r"\b(" + "|".join(WEEKDAYS_DE + WEEKDAYS_EN) + r")\b", re.IGNORECASE)


def parse_point(word: str) -> str:
    point = word.lower()
    if point not in SCHEDULE_POINTS:
        raise CommandError(UNKNOWN_POINT.format(point=word))
    return point


def parse_weekly_time(day: str, clock: str) -> WeeklyTime:
    weekday = WEEKDAY_NAMES.get(day.lower())
    if weekday is None:
        raise CommandError(UNKNOWN_WEEKDAY.format(day=day))
    match = _TIME.fullmatch(clock)
    try:
        if match is None:
            raise ValueError
        parsed = time(int(match[1]), int(match[2]))
    except ValueError:
        raise CommandError(BAD_TIME.format(time=clock)) from None
    return WeeklyTime(weekday, parsed)


# --- The guard ----------------------------------------------------------------------------------


def _apply(ctx: CommandContext, overrides: Mapping[str, str], prefix: str = "") -> Config:
    """`ctx.base` with `overrides`; CommandError (in German) if the schedule order breaks."""
    try:
        return apply_overrides(ctx.base, overrides)
    except ConfigError as error:
        match = _ORDER_ERROR.match(str(error))
        if match is None:
            raise CommandError(prefix + ORDER_BROKEN_GENERIC) from None
        raise CommandError(prefix + ORDER_BROKEN.format(first=match[1], second=match[2])) from None


def check_change(
    ctx: CommandContext, overrides: Mapping[str, str], *, keep_pending: bool = True
) -> Config:
    """The effective config under `overrides`, if the change from `ctx.config` is allowed.

    `overrides` are those in effect right away (see `current_values`). Raises CommandError (in
    German) if
    1. the schedule order breaks — also under a pending new dinner weekday, unless the change
       discards it (`keep_pending=False`),
    2. the current dinner week changes, or
    3. a step of the current week that is not recorded yet is due at `now` under the new config
       but was not under the old one. Exception: a nudge that would already be past its window
       (it would only be recorded as skipped, nothing is sent).
    """
    old = ctx.config
    new = _apply(ctx, overrides)
    pending = pending_dinner(ctx.base, ctx.store, ctx.now) if keep_pending else None
    if pending is not None:
        prefix = WITH_NEW_DINNER.format(when=ui.weekly_time(pending.point), first=_first(pending))
        future = _apply(ctx, {**overrides, DINNER_KEY: format_weekly_time(pending.point)}, prefix)
        try:
            transition(future, pending.switch)
        except ValueError:
            raise CommandError(prefix + DINNER_DAY_UNSAFE) from None

    week, new_week = dinner_week(old, ctx.now), dinner_week(new, ctx.now)
    if new_week != week:
        raise CommandError(WEEK_MOVES.format(old=_date(week), new=_date(new_week)))

    old_windows = {w.name: w for w in step_windows(old, week)}
    for window in step_windows(new, week):
        if any(ctx.store.has_action(week, action) for action in window.actions):
            continue
        due = window.due(ctx.now)
        if due is None:
            continue
        before = old_windows.get(window.name)
        if before is not None and before.due(ctx.now) is not None:
            continue  # already due before this change; not caused by it
        if window.name == "nudge" and due is False:
            continue  # past its window: the engine only records it as skipped
        raise CommandError(STEP_DUE.format(step=STEP_LABELS[window.name]))
    return new


# --- Replies ------------------------------------------------------------------------------------


def _date(day: date) -> str:
    return f"{day:%d.%m.}"


def _day(day: date) -> str:
    """``Mo 19.10.``"""
    return f"{ui.WEEKDAYS_SHORT[day.weekday()]} {day:%d.%m.}"


def _moment(moment: datetime) -> str:
    """``Sa 24.10. um 18:00``"""
    return f"{ui.WEEKDAYS_SHORT[moment.weekday()]} {moment:%d.%m. um %H:%M}"


def _first(pending: PendingDinner) -> str:
    """The first dinner under a pending dinner weekday: ``Sa 24.10.``."""
    return _day(pending.transition.first_week)


def _point(config: Config, point: str) -> WeeklyTime:
    return getattr(config.schedule, "nudge_time" if point == "nudge" else point)


# The engine step each schedule point triggers; the other points only appear in the texts.
_STEP_ACTIONS = {
    "flat_ask": (Action.FLAT_ASK,),
    "nudge": (Action.NUDGE,),
    "flat_deadline": (Action.ANNOUNCEMENT, Action.CANCELLATION),
    "tally": (Action.TALLY,),
}


def _done(ctx: CommandContext, week: date, point: str) -> bool:
    """Whether the step `point` triggers is already recorded for `week`."""
    return any(ctx.store.has_action(week, action) for action in _STEP_ACTIONS.get(point, ()))


def _occurrence(ctx: CommandContext, config: Config, point: str) -> datetime:
    """The next time `point` happens, in the config's timezone: this week's, unless it is past
    or its step is already done; else next week's."""
    week = dinner_week(config, ctx.now)
    when = config.when(_point(config, point), week)
    if when <= ctx.now or _done(ctx, week, point):
        when = config.when(_point(config, point), week + timedelta(weeks=1))
    return when


def _point_line(ctx: CommandContext, config: Config, point: str) -> str:
    nxt = _occurrence(ctx, config, point)
    return POINT_LINE.format(
        label=POINT_LABELS[point],
        point=point,
        when=ui.weekly_time(_point(config, point)),
        next=f"{ui.WEEKDAYS_SHORT[nxt.weekday()]} {nxt:%d.%m. um %H:%M}",
    )


def _affects_this_week(ctx: CommandContext, new: Config, point: str) -> bool:
    """Whether `point` changes this week: its time (or the nudge's on/off) changes, it is not in
    the past under both configs, and its step is not done yet."""
    week = dinner_week(ctx.config, ctx.now)
    if _done(ctx, week, point):
        return False
    before = ctx.config.when(_point(ctx.config, point), week)
    after = new.when(_point(new, point), week)
    enabled_changed = point == "nudge" and (
        ctx.config.schedule.nudge_enabled != new.schedule.nudge_enabled
    )
    if before == after and not enabled_changed:
        return False
    return max(before, after) > ctx.now


def _warnings(ctx: CommandContext, new: Config) -> list[str]:
    lines: list[str] = []
    before, after = ctx.config.schedule, new.schedule
    week = dinner_week(ctx.config, ctx.now)
    # The flat ask names the deadline; it is out, and the decision is still to come.
    asked = ctx.store.action_outcome(week, Action.FLAT_ASK) is Outcome.SENT
    if (
        before.flat_deadline != after.flat_deadline
        and asked
        and not _done(ctx, week, "flat_deadline")
    ):
        lines.append(
            ASK_ALREADY_SENT.format(
                old=ui.weekly_time(before.flat_deadline), new=ui.weekly_time(after.flat_deadline)
            )
        )
    # The announcement names rsvp_by, cook and dinner; it is out, and dinner is still to come.
    announced = ctx.store.action_outcome(week, Action.ANNOUNCEMENT) is Outcome.SENT
    if announced:
        for point in ("rsvp_by", "cook", "dinner"):
            if getattr(before, point) != getattr(after, point):
                lines.append(
                    ANNOUNCEMENT_ALREADY_SENT.format(
                        point=point,
                        old=ui.weekly_time(getattr(before, point)),
                        new=ui.weekly_time(getattr(after, point)),
                    )
                )
    return lines + _hardcoded_weekdays(new)


def _hardcoded_weekdays(config: Config) -> list[str]:
    return [
        HARDCODED_WEEKDAY.format(name=name)
        for name in EDITABLE_TEMPLATES
        if _HARDCODED_DAY.search(getattr(config.templates, name).text)
    ]


def _reply(ctx: CommandContext, new: Config, point: str, headline: str) -> list[str]:
    lines = [headline]
    if point == "nudge" and not new.schedule.nudge_enabled:
        lines.append(NUDGE_OFF_LINE)
        if ctx.config.schedule.nudge_time != new.schedule.nudge_time:
            lines.append(NUDGE_OFF_NOTE)
    else:
        lines.append(_point_line(ctx, new, point))
    lines.append(THIS_WEEK if _affects_this_week(ctx, new, point) else FROM_NEXT_WEEK)
    lines += _warnings(ctx, new)
    return ["\n".join(lines)]


def _changed_by(ctx: CommandContext) -> str:
    return ctx.sender_name or ctx.sender


# --- Commands -----------------------------------------------------------------------------------


def set_dinner_day(ctx: CommandContext, value: str | None, headline: str) -> list[str]:
    """Move dinner to another weekday: to `value`, or back to the config file's (None).

    Never touches the running dinner week. If it has started (its flat ask is due, or anything of
    it is recorded), the change is stored as pending until the week's dinner; else it applies at
    once. Either way, the first week of the new weekday starts cleanly after the switch, or is
    dropped as a whole (see `odin.engine.transition`); the reply names the first dinner and warns
    about a dropped one.
    """
    stored = current_values(ctx.store)
    if value is None:
        stored.pop(DINNER_KEY, None)
        new = _apply(ctx, stored)
    else:
        new = _apply(ctx, stored | {DINNER_KEY: value})
    old = ctx.config
    week = dinner_week(old, ctx.now)
    started = ctx.store.has_any_action(week) or old.when(old.schedule.flat_ask, week) <= ctx.now
    switch = old.when(old.schedule.dinner, week) if started else ctx.now
    try:
        weeks = transition(new, switch)
    except ValueError:
        raise CommandError(DINNER_DAY_UNSAFE) from None
    if any(
        ctx.store.has_any_action(w) for w in (weeks.first_week, weeks.dropped_week) if w is not None
    ):
        raise CommandError(DINNER_DAY_UNSAFE)  # an earlier weekday change left records there

    target = format_weekly_time(new.schedule.dinner)
    with ctx.store.transaction():
        if started:
            ctx.store.set_override(
                PENDING_DINNER_KEY, target, _changed_by(ctx), ctx.now, after_week=week
            )
        else:
            ctx.store.delete_override(PENDING_DINNER_KEY)
            if value is None:
                ctx.store.delete_override(DINNER_KEY)
            else:
                ctx.store.set_override(DINNER_KEY, target, _changed_by(ctx), ctx.now)
            # A pending change is recorded when it applies (`odin.overrides.effective_config`).
            record_transition(ctx.store, weeks)

    first = _moment(new.when(new.schedule.dinner, weeks.first_week))
    lines = [
        headline,
        DINNER_MOVED.format(
            old=ui.weekly_time(old.schedule.dinner), new=ui.weekly_time(new.schedule.dinner)
        ),
    ]
    if started:
        this = _moment(old.when(old.schedule.dinner, week))
        lines.append(DINNER_FROM_NEXT.format(first=first, this=this))
    else:
        lines.append(DINNER_FROM_NOW.format(first=first))
    if weeks.dropped_week is not None:
        day = _day(weeks.dropped_week)
        lines.append(DINNER_WEEK_DROPPED.format(day=day))
        if started:
            lines.append(DROPPED_CANCELLATION_LATER.format(day=day, switch=this))
        else:
            lines.append(DROPPED_CANCELLATION_NOW.format(day=day))
    lines += _hardcoded_weekdays(new)
    return ["\n".join(lines)]


def run_settime(ctx: CommandContext, args: str) -> list[str]:
    words = args.split()
    if len(words) != 3:
        raise CommandError(SETTIME_USAGE)
    point = parse_point(words[0])
    when = parse_weekly_time(words[1], words[2])
    value = format_weekly_time(when)
    if point == "dinner" and when.weekday != ctx.config.schedule.dinner.weekday:
        return set_dinner_day(ctx, value, SAVED)
    key = schedule_key(point)
    # The latest /settime dinner wins: a new time on today's weekday discards a pending one.
    pending = pending_dinner(ctx.base, ctx.store, ctx.now) if point == "dinner" else None
    new = check_change(ctx, current_values(ctx.store) | {key: value}, keep_pending=pending is None)
    with ctx.store.transaction():
        ctx.store.set_override(key, value, _changed_by(ctx), ctx.now)
        if pending is not None:
            ctx.store.delete_override(PENDING_DINNER_KEY)
    [reply] = _reply(ctx, new, point, SAVED)
    if pending is None:
        return [reply]
    discarded = PENDING_DISCARDED.format(new=ui.weekly_time(pending.point), first=_first(pending))
    return [f"{reply}\n{discarded}"]


def run_nudge(ctx: CommandContext, args: str) -> list[str]:
    words = args.split()
    if len(words) != 1 or words[0].lower() not in _ON:
        raise CommandError(NUDGE_USAGE)
    value = format_bool(_ON[words[0].lower()])
    new = check_change(ctx, current_values(ctx.store) | {NUDGE_ENABLED_KEY: value})
    ctx.store.set_override(NUDGE_ENABLED_KEY, value, _changed_by(ctx), ctx.now)
    return _reply(ctx, new, "nudge", SAVED)


def run_resettime(ctx: CommandContext, args: str) -> list[str]:
    words = args.split()
    if len(words) != 1:
        raise CommandError(RESETTIME_USAGE)
    point = parse_point(words[0])
    if point == "dinner":
        pending = pending_dinner(ctx.base, ctx.store, ctx.now)
        if pending is not None:
            ctx.store.delete_override(PENDING_DINNER_KEY)
            headline = PENDING_CANCELLED.format(
                new=ui.weekly_time(pending.point), first=_first(pending)
            )
            return [f"{headline}\n{_point_line(ctx, ctx.config, point)}"]
    keys = [schedule_key(point)] + ([NUDGE_ENABLED_KEY] if point == "nudge" else [])
    stored = current_values(ctx.store)
    if (
        point == "dinner"
        and DINNER_KEY in stored
        and ctx.base.schedule.dinner.weekday != ctx.config.schedule.dinner.weekday
    ):
        return set_dinner_day(ctx, None, RESET)
    if not any(key in stored for key in keys):
        when = ui.weekly_time(_point(ctx.config, point))
        if point == "nudge":
            state = "an" if ctx.config.schedule.nudge_enabled else "aus"
            return [NUDGE_NOT_OVERRIDDEN.format(state=state, when=when)]
        return [NOT_OVERRIDDEN.format(label=POINT_LABELS[point], point=point, when=when)]
    new = check_change(ctx, {k: v for k, v in stored.items() if k not in keys})
    for key in keys:
        ctx.store.delete_override(key)
    return _reply(ctx, new, point, RESET)


SETTIME = Command(
    name="settime",
    usage="/settime <punkt> <tag> <HH:MM>",
    summary="Verschiebt einen Zeitpunkt im Wochenplan.",
    run=run_settime,
)
NUDGE = Command(
    name="nudge",
    usage="/nudge on|off",
    summary="Schaltet die Erinnerung an die WG an oder aus.",
    run=run_nudge,
)
RESETTIME = Command(
    name="resettime",
    usage="/resettime <punkt>",
    summary="Setzt einen Zeitpunkt auf den Wert aus der Config zurück.",
    run=run_resettime,
)
