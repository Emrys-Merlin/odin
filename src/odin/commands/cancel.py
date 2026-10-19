"""/cancel: cancel this week's dinner from the chat, after a confirming reaction.

`/cancel` itself sends nothing to the dinner group. ODIN replies with what it would post and asks
for the configured emoji (👍) on that reply; the reply is tracked as the week's cancel request
(see `TrackedReply`). Once anyone in the flat group reacts, the engine posts the cancellation on
its next tick and records it like any other step, so it goes out at most once (see
`odin.engine`). The request belongs to the dinner week it was made in and lapses when that
week's dinner starts.

Refused when the dinner group has already been told the week is off (or ODIN deliberately did
not tell it), for a week dropped by a dinner weekday change (its cancellation goes out anyway),
and while a request of this week is open.
"""

from datetime import UTC, datetime

from odin.commands import ui
from odin.commands.core import Command, CommandContext, CommandError, TrackedReply
from odin.config import WEEKDAYS_DE
from odin.engine import dinner_week
from odin.reactions import count_confirmations
from odin.store import Action, MessageKind, Outcome

USAGE = "So geht's: einfach /cancel, ohne Zusatz."
CONFIRM = (
    "Das Essen am {day} absagen? Dann reagiert mit {emoji} auf diese Nachricht – "
    "ich schicke der Essensgruppe dann diese Absage:"
)
ALREADY_ANNOUNCED = "Die Einladung ist schon raus ({reactions}); die Absage kommt dann hinterher."
LAPSES = "Ohne {emoji} passiert nichts; die Anfrage verfällt, wenn das Essen beginnt ({dinner})."
ALREADY_CANCELLED = "Das Essen am {day} ist schon abgesagt (Absage gesendet {at})."
CANCELLATION_SKIPPED = (
    "Für das Essen am {day} habe ich die Absage übersprungen (ich war zu spät dran) und schicke "
    "jetzt auch keine mehr. Sagt der Essensgruppe bitte selbst Bescheid."
)
DROPPED_WEEK = (
    "Das Essen am {day} fällt schon wegen des Wechsels des Essenstags aus; "
    "die Absage an die Essensgruppe schicke ich ohnehin."
)
ALREADY_REQUESTED = (
    "Die Absage für das Essen am {day} ist schon angefragt ({at}) – "
    "reagiert mit {emoji} auf meine Nachricht von da."
)


def run(ctx: CommandContext, args: str) -> list[str]:
    if args:
        raise CommandError(USAGE)
    config, store = ctx.config, ctx.store
    week = dinner_week(config, ctx.now)
    day = f"{WEEKDAYS_DE[week.weekday()]}, {week:%d.%m.}"

    def local(moment: datetime) -> str:
        at = moment.astimezone(config.timezone)
        return f"{ui.WEEKDAYS_SHORT[at.weekday()]} {at:%d.%m. %H:%M}"

    match store.action_outcome(week, Action.CANCELLATION):
        case Outcome.SENT:
            sent_at = store.action_time(week, Action.CANCELLATION)
            assert sent_at is not None
            raise CommandError(ALREADY_CANCELLED.format(day=day, at=local(sent_at)))
        case Outcome.SKIPPED:
            raise CommandError(CANCELLATION_SKIPPED.format(day=day))
    if store.dropped_at(week) is not None:
        raise CommandError(DROPPED_WEEK.format(day=day))
    request = store.tracked_message(week, MessageKind.CANCEL_REQUEST)
    if request is not None:
        requested_at = datetime.fromtimestamp(request.timestamp / 1000, UTC)
        raise CommandError(
            ALREADY_REQUESTED.format(day=day, at=local(requested_at), emoji=config.emoji)
        )

    lines = [CONFIRM.format(day=day, emoji=config.emoji)]
    announcement = store.tracked_message(week, MessageKind.DINNER_ANNOUNCEMENT)
    if store.action_outcome(week, Action.ANNOUNCEMENT) is Outcome.SENT:
        if announcement is None:
            reactions = ui.UNTRACKED.format(emoji=config.emoji)
        else:
            count = count_confirmations(store, announcement, config.emoji)
            reactions = f"{count}× {config.emoji}"
        lines.append(ALREADY_ANNOUNCED.format(reactions=reactions))
    dinner = config.when(config.schedule.dinner, week)
    lines.append(LAPSES.format(emoji=config.emoji, dinner=local(dinner)))
    cancellation = config.templates.cancellation.render(**config.placeholder_values())
    text = "\n".join(lines) + "\n\n" + cancellation
    return [TrackedReply(text, week, MessageKind.CANCEL_REQUEST)]


CANCEL = Command(
    name="cancel",
    usage="/cancel",
    summary="Sagt das Essen dieser Woche ab – nach Bestätigung per Reaktion.",
    run=run,
)
