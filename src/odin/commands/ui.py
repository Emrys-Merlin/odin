"""German UI strings shared by several commands.

Command replies are UI strings in code, not config templates; the config holds only the messages
of the weekly cycle. Strings that a single command uses live in that command's module.
"""

from datetime import datetime, tzinfo

from odin.config import WeeklyTime

HELP_HINT = "/help zeigt alle Befehle."
UNKNOWN_COMMAND = "Unbekannter Befehl {command} – " + HELP_HINT
GENERIC_ERROR = "Da ist etwas schiefgegangen – bitte später nochmal versuchen."
# Reactions on a message that was sent but is not tracked (its timestamp could not be read).
UNTRACKED = "{emoji} nicht zählbar"

WEEKDAYS_SHORT = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def weekly_time(point: WeeklyTime) -> str:
    """A schedule point in German: ``Di 18:00``."""
    return f"{WEEKDAYS_SHORT[point.weekday]} {point.time:%H:%M}"


def override_marker(changed_by: str, changed_at: datetime, timezone: tzinfo) -> str:
    """Marks a value changed via chat: ``✏️ 12.10. von Tim``, the date taken in ``timezone``."""
    return f"✏️ {changed_at.astimezone(timezone):%d.%m.} von {changed_by}"
