"""/schedule: the weekly schedule, one line per point, with overridden values marked."""

from odin.commands import ui
from odin.commands.core import Command, CommandContext
from odin.config import Schedule, WeeklyTime
from odin.overrides import NUDGE_ENABLED_KEY, SCHEDULE_POINTS, schedule_key

# German descriptions of the schedule points, in schedule order.
POINT_DESCRIPTIONS: dict[str, str] = {
    "flat_ask": "Frage an die WG",
    "nudge": "Erinnerung",
    "flat_deadline": "Entscheidung",
    "rsvp_by": "Rückmeldung bis",
    "tally": "Zählung",
    "cook": "Mitkochen",
    "dinner": "Essen",
}

NUDGE_OFF = "(aus)"
FOOTER = "Ändern: /settime <punkt> <tag> <HH:MM> · Zurücksetzen: /resettime <punkt>"


def point_time(schedule: Schedule, point: str) -> WeeklyTime:
    """The time of schedule point `point` (one of `SCHEDULE_POINTS`); the nudge's even if off."""
    return schedule.nudge_time if point == "nudge" else getattr(schedule, point)


def run(ctx: CommandContext, args: str) -> list[str]:
    schedule = ctx.config.schedule
    overrides = ctx.store.overrides()
    lines = []
    for point in SCHEDULE_POINTS:
        when = ui.weekly_time(point_time(schedule, point))
        line = f"{point} – {POINT_DESCRIPTIONS[point]}: {when}"
        keys = [schedule_key(point)]
        if point == "nudge":
            if not schedule.nudge_enabled:
                line += f" {NUDGE_OFF}"
            keys.append(NUDGE_ENABLED_KEY)
        # The nudge has two overridable values (time, on/off); the latest change is shown.
        changes = [overrides[key] for key in keys if key in overrides]
        if changes:
            latest = max(changes, key=lambda o: o.changed_at)
            line += " " + ui.override_marker(
                latest.changed_by, latest.changed_at, ctx.config.timezone
            )
        lines.append(line)
    return ["\n".join([*lines, "", FOOTER])]


SCHEDULE = Command(name="schedule", usage="/schedule", summary="Zeigt den Wochenplan.", run=run)
