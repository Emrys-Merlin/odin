"""Messages to the flat group about ODIN itself, not part of the weekly cycle.

They are German UI strings in code, like the chat-command replies: they explain a fault of ODIN,
so flatmates have no reason to edit them, and they must work whatever the templates say. They
use the placeholders of the weekly templates (`Config.placeholder_values`) and ``{tally}``.

A tracked message (flat poll, announcement) can go out without ODIN learning which message it
was (`odin.signal.SendResponseUnreadable`); the reactions to it cannot be counted then. These
notices tell the flat group, once:

- **flat ask retry** — asks again; this message is tracked as the week's flat poll instead, so
  confirming on it works as usual (`odin.engine`).
- **announcement notice** — the guests' reactions cannot be counted, so the tally shows 0; the
  flatmates count by hand.
"""

from odin.config import WEEKDAYS_DE, Config

FLAT_ASK_RETRY = (
    "⚠️ Meine Frage zum Essen am {dinner_day_de} ist rausgegangen, aber ich kann die {emoji} "
    "darauf nicht zählen (Signal hat mir nicht gesagt, welche Nachricht es war).\n"
    "Bitte reagiert stattdessen auf diese Nachricht mit {emoji}, wenn das Essen stattfindet – "
    "bis {deadline_day_de} {deadline}. Ohne {emoji} hier sage ich das Essen ab."
)
ANNOUNCEMENT_NOTICE = (
    "⚠️ Die Einladung zum Essen am {dinner_day_de} ist in der Essensgruppe rausgegangen, aber "
    "ich kann die {emoji} darauf nicht zählen (Signal hat mir nicht gesagt, welche Nachricht es "
    "war). Die Zählung am {tally} zeigt deshalb 0 – bitte zählt die {emoji} unter der Einladung "
    "selbst."
)


def render(text: str, config: Config) -> str:
    tally = config.schedule.tally
    return text.format(
        **config.placeholder_values(),
        tally=f"{WEEKDAYS_DE[tally.weekday]} um {tally.time:%H:%M}",
    )
