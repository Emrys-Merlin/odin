"""/settime, /nudge and /resettime: move the points of the weekly schedule from the chat.

A change takes effect at once, but it is guarded: it is rejected (and nothing is stored) if it
breaks the order of the schedule, moves the current dinner week, or makes a step of the current
week that has not happened yet due right now. See `check_change`.
"""

import re
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta

from odin.commands import ui
from odin.commands.core import Command, CommandContext, CommandError
from odin.config import WEEKDAYS_DE, WEEKDAYS_EN, Config, ConfigError, WeeklyTime
from odin.engine import dinner_week, step_windows
from odin.overrides import (
    EDITABLE_TEMPLATES,
    NUDGE_ENABLED_KEY,
    SCHEDULE_POINTS,
    apply_overrides,
    format_bool,
    format_weekly_time,
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
WEEK_MOVES = (
    "Damit würde sich die aktuelle Essenswoche verschieben (Essen am {old} → {new}) – "
    "das geht nicht über den Chat."
)
# A dinner on another weekday is always another dinner week (weeks are named by their dinner date).
DINNER_DAY = (
    "Den Wochentag des Essens kann ich über den Chat nicht ändern, nur die Uhrzeit – "
    "sonst wäre es eine andere Essenswoche. Das geht nur in der Config."
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


def _stored(ctx: CommandContext) -> dict[str, str]:
    return {key: override.value for key, override in ctx.store.overrides().items()}


def check_change(ctx: CommandContext, overrides: Mapping[str, str]) -> Config:
    """The effective config under `overrides`, if the change from `ctx.config` is allowed.

    Raises CommandError (in German) if
    1. the schedule order breaks,
    2. the current dinner week changes, or
    3. a step of the current week that is not recorded yet is due at `now` under the new config
       but was not under the old one. Exception: a nudge that would already be past its window
       (it would only be recorded as skipped, nothing is sent).
    """
    old = ctx.config
    try:
        new = apply_overrides(ctx.base, overrides)
    except ConfigError as error:
        match = _ORDER_ERROR.match(str(error))
        if match is None:
            raise CommandError(ORDER_BROKEN_GENERIC) from None
        raise CommandError(ORDER_BROKEN.format(first=match[1], second=match[2])) from None

    week, new_week = dinner_week(old, ctx.now), dinner_week(new, ctx.now)
    if new_week != week:
        if new.schedule.dinner.weekday != old.schedule.dinner.weekday:
            raise CommandError(DINNER_DAY)
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
    for name in EDITABLE_TEMPLATES:
        if _HARDCODED_DAY.search(getattr(new.templates, name).text):
            lines.append(HARDCODED_WEEKDAY.format(name=name))
    return lines


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


def run_settime(ctx: CommandContext, args: str) -> list[str]:
    words = args.split()
    if len(words) != 3:
        raise CommandError(SETTIME_USAGE)
    point = parse_point(words[0])
    value = format_weekly_time(parse_weekly_time(words[1], words[2]))
    key = schedule_key(point)
    new = check_change(ctx, _stored(ctx) | {key: value})
    ctx.store.set_override(key, value, _changed_by(ctx), ctx.now)
    return _reply(ctx, new, point, SAVED)


def run_nudge(ctx: CommandContext, args: str) -> list[str]:
    words = args.split()
    if len(words) != 1 or words[0].lower() not in _ON:
        raise CommandError(NUDGE_USAGE)
    value = format_bool(_ON[words[0].lower()])
    new = check_change(ctx, _stored(ctx) | {NUDGE_ENABLED_KEY: value})
    ctx.store.set_override(NUDGE_ENABLED_KEY, value, _changed_by(ctx), ctx.now)
    return _reply(ctx, new, "nudge", SAVED)


def run_resettime(ctx: CommandContext, args: str) -> list[str]:
    words = args.split()
    if len(words) != 1:
        raise CommandError(RESETTIME_USAGE)
    point = parse_point(words[0])
    keys = [schedule_key(point)] + ([NUDGE_ENABLED_KEY] if point == "nudge" else [])
    stored = _stored(ctx)
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
