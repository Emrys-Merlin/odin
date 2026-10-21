"""Chat commands: ``/name args`` or ``!name args`` in the flat group, answered in German.

Senders on `commands.direct_senders` may also send them in a direct message (`handle_direct`).

Every command lives in its own module and is registered in `COMMANDS` below. The interface
(`CommandContext`, `Command`, `CommandError`) is defined in `odin.commands.core`.
"""

from dataclasses import dataclass

from odin.commands import ui
from odin.commands.cancel import CANCEL
from odin.commands.core import Command, CommandContext, CommandError, TrackedReply, parse
from odin.commands.help import HELP
from odin.commands.hiatus import HIATUS, RESUME
from odin.commands.introduce import INTRODUCE
from odin.commands.schedule import SCHEDULE
from odin.commands.settext import RESETTEXT, SETTEXT
from odin.commands.settime import NUDGE, RESETTIME, SETTIME
from odin.commands.skip import SKIP, UNSKIP
from odin.commands.status import STATUS
from odin.commands.texts import TEXT, TEXTS
from odin.commands.vars import VARS
from odin.commands.version import VERSION

__all__ = [
    "COMMANDS",
    "Command",
    "CommandContext",
    "CommandError",
    "DirectAnswer",
    "TrackedReply",
    "handle",
    "handle_direct",
]

# The registry, in the order /help lists the commands. One line per command.
COMMANDS: list[Command] = [
    HELP,
    STATUS,
    SCHEDULE,
    TEXTS,
    TEXT,
    SETTEXT,
    RESETTEXT,
    VARS,
    SETTIME,
    RESETTIME,
    NUDGE,
    CANCEL,
    SKIP,
    UNSKIP,
    INTRODUCE,
    HIATUS,
    RESUME,
    VERSION,
]


# The longest command line a notice quotes.
NOTICE_LENGTH = 80


@dataclass(frozen=True)
class DirectAnswer:
    replies: list[str]  # to the sender, as direct messages
    notice: str | None = None  # to the flat group


def handle(text: str, ctx: CommandContext) -> list[str]:
    """Replies to a group message; [] if the text is not a command."""
    invocation = parse(text)
    if invocation is None:
        return []
    command = _find(invocation.name)
    if command is None:
        return [ui.UNKNOWN_COMMAND.format(command=invocation.word)]
    try:
        return command.run(ctx, invocation.args)
    except CommandError as error:
        return [str(error)]


def handle_direct(text: str, ctx: CommandContext) -> DirectAnswer:
    """The answer to a direct message from an allowed sender (`ctx.direct` is set).

    A text that is not a command gets a hint. A `group_only` command is refused before it runs,
    and so is any reply that would need a confirmation (`/skip` of the running week is
    `/cancel`): reactions count only in the flat group. A `changes` command that wrote to the
    store gets a notice for the flat group, unless `commands.direct_notice` is off.
    """
    invocation = parse(text)
    if invocation is None:
        return DirectAnswer([ui.DIRECT_NOT_A_COMMAND])
    command_line = _shorten(text.strip().splitlines()[0])
    refused = DirectAnswer(
        [ui.DIRECT_GROUP_ONLY.format(command=command_line, emoji=ctx.config.emoji)]
    )
    command = _find(invocation.name)
    if command is not None and command.group_only:
        return refused
    written = ctx.store.changes
    replies = handle(text, ctx)
    if any(isinstance(reply, TrackedReply) for reply in replies):
        return refused
    if (
        command is None
        or not command.changes
        or ctx.store.changes == written
        or not ctx.config.commands.direct_notice
    ):
        return DirectAnswer(replies)
    notice = ui.DIRECT_NOTICE.format(name=ctx.sender_name or ctx.sender, command=command_line)
    return DirectAnswer(replies, notice)


def _find(name: str) -> Command | None:
    return next((c for c in COMMANDS if c.name == name), None)


def _shorten(line: str) -> str:
    return line if len(line) <= NOTICE_LENGTH else line[: NOTICE_LENGTH - 1].rstrip() + "…"
