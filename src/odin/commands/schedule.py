"""/schedule: the weekly schedule, one line per point, with overridden values marked.

The decision (`flat_deadline`) is marked while the cancellation to the dinner group is switched off.
A pending new dinner weekday is shown on the dinner line, with its first dinner and a dropped week,
also one that comes from the config file.
"""

from odin.commands import ui
from odin.commands.core import Command, CommandContext
from odin.cycle import SchedulePoint
from odin.overrides import (
    CANCELLATION_ENABLED_KEY,
    NUDGE_ENABLED_KEY,
    PENDING_DINNER_KEY,
    pending_dinner,
    schedule_key,
)

# German descriptions of the schedule points, in schedule order.
POINT_DESCRIPTIONS: dict[SchedulePoint, str] = {
    SchedulePoint.FLAT_ASK: "Frage an die WG",
    SchedulePoint.NUDGE: "Erinnerung",
    SchedulePoint.FLAT_DEADLINE: "Entscheidung",
    SchedulePoint.RSVP_BY: "Rückmeldung bis",
    SchedulePoint.TALLY: "Zählung",
    SchedulePoint.COOK: "Mitkochen",
    SchedulePoint.DINNER: "Essen",
}

NUDGE_OFF = "(aus)"
CANCELLATION_OFF = "(ohne Absage an die Essensgruppe)"
PENDING = "→ ab {first:%d.%m.}: {when}"
DROPPED = "({weekday} {day:%d.%m.} entfällt)"
FROM_CONFIG = "(laut Config-Datei)"
FOOTER = "Ändern: /settime <punkt> <tag> <HH:MM> · Zurücksetzen: /resettime <punkt>"


def run(ctx: CommandContext, args: str) -> list[str]:
    schedule = ctx.config.schedule
    overrides = ctx.store.overrides()
    pending = pending_dinner(ctx.base, ctx.store, ctx.now)
    lines = []
    for point in SchedulePoint:
        when = ui.weekly_time(schedule.time_of(point))
        line = f"{point} – {POINT_DESCRIPTIONS[point]}: {when}"
        keys = [schedule_key(point)]
        if point is SchedulePoint.NUDGE:
            if not schedule.nudge_enabled:
                line += f" {NUDGE_OFF}"
            keys.append(NUDGE_ENABLED_KEY)
        if point is SchedulePoint.FLAT_DEADLINE:
            if not ctx.config.decision.cancellation:
                line += f" {CANCELLATION_OFF}"
            keys.append(CANCELLATION_ENABLED_KEY)
        if point is SchedulePoint.DINNER and pending is not None:
            first = pending.transition.first_week
            line += " " + PENDING.format(first=first, when=ui.weekly_time(pending.point))
            dropped = pending.transition.dropped_week
            if dropped is not None:
                weekday = ui.WEEKDAYS_SHORT[dropped.weekday()]
                line += " " + DROPPED.format(weekday=weekday, day=dropped)
            if pending.from_config:
                line += " " + FROM_CONFIG
            keys.append(PENDING_DINNER_KEY)
        # The nudge has two overridable values (time, on/off), the decision its time and whether
        # it cancels, dinner a current and a pending one; the latest change is shown.
        changes = [overrides[key] for key in keys if key in overrides]
        if changes:
            latest = max(changes, key=lambda o: o.changed_at)
            line += " " + ui.override_marker(
                latest.changed_by, latest.changed_at, ctx.config.timezone
            )
        lines.append(line)
    return ["\n".join([*lines, "", FOOTER])]


SCHEDULE = Command(name="schedule", usage="/schedule", summary="Zeigt den Wochenplan.", run=run)
