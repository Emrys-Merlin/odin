"""German UI strings shared by several commands.

Command replies are UI strings in code, not config templates; the config holds only the messages
of the weekly cycle. Strings that a single command uses live in that command's module.
"""

from datetime import date, datetime, tzinfo

from odin.config import WeeklyTime
from odin.cycle import TemplateName

HELP_HINT = "/help zeigt alle Befehle."
UNKNOWN_COMMAND = "Unbekannter Befehl {command} – " + HELP_HINT
GENERIC_ERROR = "Da ist etwas schiefgegangen – bitte später nochmal versuchen."
# Reactions on a message that was sent but is not tracked (its timestamp could not be read).
UNTRACKED = "{emoji} nicht zählbar"

WEEKDAYS_SHORT = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")

# An optional template without a fallback that is not set (`introduction`).
NOT_SET = (
    "{name} ist nicht gesetzt. Anlegen: /settext {name} – und in den Zeilen darunter der Text."
)


def editable_template(word: str) -> TemplateName | None:
    """The template named `word` (in any case) if it can be changed via chat, else None."""
    try:
        name = TemplateName(word.lower())
    except ValueError:
        return None
    return name if name.editable else None


def weekly_time(point: WeeklyTime) -> str:
    """A schedule point in German: ``Di 18:00``."""
    return f"{WEEKDAYS_SHORT[point.weekday]} {point.time:%H:%M}"


def moment(at: datetime, timezone: tzinfo) -> str:
    """A moment in ``timezone``, in German: ``Di 06.10. 18:00``."""
    local = at.astimezone(timezone)
    return f"{WEEKDAYS_SHORT[local.weekday()]} {local:%d.%m. %H:%M}"


def short_date(day: date) -> str:
    """A day with its year: ``So 27.12.2026``."""
    return f"{WEEKDAYS_SHORT[day.weekday()]} {day:%d.%m.%Y}"


def override_marker(changed_by: str, changed_at: datetime, timezone: tzinfo) -> str:
    """Marks a value changed via chat: ``✏️ 12.10. von Tim``, the date taken in ``timezone``."""
    return f"✏️ {changed_at.astimezone(timezone):%d.%m.} von {changed_by}"
