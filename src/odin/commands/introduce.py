"""/introduce: ODIN introduces itself in the dinner group, after a confirming reaction.

`/introduce` itself sends nothing to the dinner group. ODIN replies with the `introduction`
template as it would post it and asks for the configured emoji (👍) on that reply; the reply is
tracked as an introduction request (see `TrackedReply`). Once anyone in the flat group reacts,
the engine posts the introduction on its next tick and records it, so each request posts it at
most once (see `odin.engine`).

Unlike `/cancel`, it is not about a dinner week: it can be sent any number of times (e.g. after
new guests joined), changes nothing in the weekly cycle and does not show in `/status`. A request
lapses `INTRODUCTION_LAPSE` after it was sent, or when a newer `/introduce` replaces it.

It is refused during a hiatus (`/hiatus`): the introduction describes the weekly cycle, which is
asleep then. A request still open when a hiatus starts is dropped by the engine, never posted.
"""

from odin.clock import to_utc
from odin.commands import ui
from odin.commands.core import Command, CommandContext, CommandError, TrackedReply
from odin.cycle import TemplateName
from odin.engine import dinner_week
from odin.reactions import INTRODUCTION_LAPSE
from odin.store import MessageKind

USAGE = "So geht's: einfach /introduce, ohne Zusatz."
CONFIRM = (
    "Soll ich mich der Essensgruppe vorstellen? Dann reagiert mit {emoji} auf diese Nachricht – "
    "ich schicke der Essensgruppe dann diesen Text:"
)
LAPSES = (
    "Ohne {emoji} passiert nichts; die Anfrage verfällt am {at} oder mit dem nächsten /introduce."
)
LAST = "Zuletzt vorgestellt: {at}."
HIATUS = "Ich mache gerade Pause – /resume beendet sie, danach kann ich mich vorstellen."


def run(ctx: CommandContext, args: str) -> list[str]:
    if args:
        raise CommandError(USAGE)
    config = ctx.config
    if ctx.store.active_hiatus() is not None:
        raise CommandError(HIATUS)
    template = config.templates.find(TemplateName.INTRODUCTION)
    if template is None:
        raise CommandError(ui.NOT_SET.format(name=TemplateName.INTRODUCTION))

    lines = [
        CONFIRM.format(emoji=config.emoji),
        LAPSES.format(
            emoji=config.emoji, at=ui.moment(to_utc(ctx.now) + INTRODUCTION_LAPSE, config.timezone)
        ),
    ]
    last = ctx.store.last_introduction()
    if last is not None:
        lines.append(LAST.format(at=ui.moment(last, config.timezone)))
    introduction = template.render(**config.placeholder_values())
    text = "\n".join(lines) + "\n\n" + introduction
    week = dinner_week(config, ctx.now)
    return [TrackedReply(text, week, MessageKind.INTRODUCTION_REQUEST)]


INTRODUCE = Command(
    name="introduce",
    usage="/introduce",
    summary="Stellt Odin der Essensgruppe vor – nach Bestätigung per Reaktion.",
    run=run,
)
