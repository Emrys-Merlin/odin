"""Chat commands: ``/name args`` or ``!name args`` in the flat group, answered in German.

Every command lives in its own module and is registered in `COMMANDS` below. The interface
(`CommandContext`, `Command`, `CommandError`) is defined in `odin.commands.core`.
"""

from odin.commands import ui
from odin.commands.cancel import CANCEL
from odin.commands.core import Command, CommandContext, CommandError, TrackedReply, parse
from odin.commands.help import HELP
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
    "TrackedReply",
    "handle",
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
    VERSION,
]


def handle(text: str, ctx: CommandContext) -> list[str]:
    """Replies to a group message; [] if the text is not a command."""
    invocation = parse(text)
    if invocation is None:
        return []
    command = next((c for c in COMMANDS if c.name == invocation.name), None)
    if command is None:
        return [ui.UNKNOWN_COMMAND.format(command=invocation.word)]
    try:
        return command.run(ctx, invocation.args)
    except CommandError as error:
        return [str(error)]
