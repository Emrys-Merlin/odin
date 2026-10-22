"""/help: list every registered command."""

from odin.commands.core import Command, CommandContext

INTRO = "Das kann ich:"
PREFIX_HINT = "Statt / geht auch !, also z. B. !help."
# Added in a direct message.
GROUP_ONLY = "Nur in der WG-Gruppe: {commands}."


def run(ctx: CommandContext, args: str) -> list[str]:
    # Imported here because the registry imports this module.
    from odin.commands import COMMANDS

    lines = [f"{command.usage} – {command.summary}" for command in COMMANDS]
    footer = [PREFIX_HINT]
    if ctx.direct:
        group_only = ", ".join(f"/{command.name}" for command in COMMANDS if command.group_only)
        footer.append(GROUP_ONLY.format(commands=group_only))
    return ["\n".join([INTRO, *lines, "", *footer])]


HELP = Command(name="help", usage="/help", summary="Zeigt alle Befehle.", run=run)
