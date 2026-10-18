"""/version: the version of ODIN that is running."""

import odin
from odin.commands.core import Command, CommandContext

REPLY = "Odin 🍽️ läuft in Version {version}."


def run(ctx: CommandContext, args: str) -> list[str]:
    # Read at call time: the version comes from the installed package metadata (see odin).
    return [REPLY.format(version=odin.__version__)]


VERSION = Command(
    name="version", usage="/version", summary="Zeigt, welche Version von Odin läuft.", run=run
)
