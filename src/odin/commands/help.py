"""/help: list every registered command."""

from odin.commands.core import Command, CommandContext

INTRO = "Das kann ich:"
PREFIX_HINT = "Statt / geht auch !, also z. B. !help."


def run(ctx: CommandContext, args: str) -> list[str]:
    # Imported here because the registry imports this module.
    from odin.commands import COMMANDS

    lines = [f"{command.usage} – {command.summary}" for command in COMMANDS]
    return ["\n".join([INTRO, *lines, "", PREFIX_HINT])]


HELP = Command(name="help", usage="/help", summary="Zeigt alle Befehle.", run=run)
