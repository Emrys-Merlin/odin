"""/settext and /resettext: change a weekly message template, or drop the change again.

``/settext <name>`` takes the new text from the lines after the command. It is validated like the
TOML (placeholders, braces) before it is stored as an override; the reply shows how it renders.
"""

from odin.commands.core import Command, CommandContext, CommandError
from odin.commands.preview import render_preview
from odin.config import (
    TEMPLATE_PLACEHOLDERS,
    Config,
    ConfigError,
    Template,
    TemplateError,
    TemplateProblem,
)
from odin.engine import dinner_week
from odin.overrides import (
    EDITABLE_TEMPLATES,
    apply_overrides,
    current_values,
    effective_config,
    template_key,
)
from odin.store import Action

NAMES = ", ".join(EDITABLE_TEMPLATES)
SETTEXT_EXAMPLE = "So geht's: /settext cancellation – und in den Zeilen darunter der neue Text."
NO_NAME = "Welcher Text? Ändern lassen sich: " + NAMES + "."
UNKNOWN_NAME = "Einen Text „{name}“ gibt es nicht. Ändern lassen sich: " + NAMES + "."
TEXT_ON_FIRST_LINE = "Der neue Text kommt in die Zeile nach /settext {name}."
EMPTY_TEXT = "Der neue Text fehlt. " + SETTEXT_EXAMPLE
RESET_EXTRA = "/resettext braucht nur den Namen, z. B. /resettext cancellation."

UNKNOWN_PLACEHOLDER = "Unbekannter Platzhalter {{{field}}}."
PLACEHOLDER_SPEC = "Der Platzhalter {{{field}}} darf kein : und kein ! enthalten."
MALFORMED = (
    "Die geschweiften Klammern passen nicht zusammen. Für eine Klammer im Text schreib {{ bzw. }}."
)
INVALID = "Der Text ist ungültig."
SEE_VARS = "Welche Platzhalter es gibt, zeigt /vars {name}."

SAVED = "Gespeichert ✅ So sieht {name} jetzt aus:"
RESET = "Zurückgesetzt auf den Standardtext ✅ So sieht {name} jetzt aus:"
NOT_CHANGED = "{name} war nicht geändert."
SAMPLE_NOTE = "(Mit der Beispielzahl 3 für {count}.)"
SAMPLE_DATES_NOTE = "(Mit Beispieldaten: als fiele das nächste Essen aus.)"
NEXT_WEEK = "Für diese Woche ist das schon gelaufen – der Text gilt ab nächster Woche."

# The weekly actions that send each template; once one of them is recorded for the current
# week, a new text only shows next week.
_ACTIONS: dict[str, tuple[Action, ...]] = {
    "flat_ask": (Action.FLAT_ASK,),
    "nudge": (Action.NUDGE,),
    "announcement": (Action.ANNOUNCEMENT, Action.CANCELLATION),
    "cancellation": (Action.ANNOUNCEMENT, Action.CANCELLATION),
    "weekday_change_cancellation": (Action.ANNOUNCEMENT, Action.CANCELLATION),
    "tally": (Action.TALLY,),
}


def _template_name(word: str) -> str:
    name = word.lower()
    if name not in EDITABLE_TEMPLATES:
        raise CommandError(UNKNOWN_NAME.format(name=word))
    return name


def _problem(name: str, text: str) -> str:
    """What is wrong with `text` as template `name`, in German."""
    try:
        Template.parse(text, TEMPLATE_PLACEHOLDERS[name], name)
    except TemplateError as error:
        match error.problem:
            case TemplateProblem.MALFORMED:
                return MALFORMED
            case TemplateProblem.UNKNOWN_PLACEHOLDER:
                return UNKNOWN_PLACEHOLDER.format(field=error.field)
            case TemplateProblem.PLACEHOLDER_SPEC:
                return PLACEHOLDER_SPEC.format(field=error.field)
    return INVALID


def _done_this_week(config: Config, ctx: CommandContext, name: str) -> bool:
    week = dinner_week(config, ctx.now)
    return any(ctx.store.has_action(week, action) for action in _ACTIONS[name])


def _replies(header: str, config: Config, ctx: CommandContext, name: str) -> list[str]:
    """`header` plus notes, then the rendered template as a message of its own."""
    preview, is_sample = render_preview(config, ctx.store, name, ctx.now)
    lines = [header]
    if is_sample:
        lines.append(SAMPLE_NOTE if name == "tally" else SAMPLE_DATES_NOTE)
    if _done_this_week(config, ctx, name):
        lines.append(NEXT_WEEK)
    return ["\n".join(lines), preview]


def settext(ctx: CommandContext, args: str) -> list[str]:
    first, _, text = args.partition("\n")
    words = first.split()
    if not words:
        raise CommandError(NO_NAME + "\n" + SETTEXT_EXAMPLE)
    name = _template_name(words[0])
    if len(words) > 1:
        raise CommandError(TEXT_ON_FIRST_LINE.format(name=name))
    text = text.strip()
    if not text:
        raise CommandError(EMPTY_TEXT)

    key = template_key(name)
    current = current_values(ctx.store)
    try:
        config = apply_overrides(ctx.base, current | {key: text})
    except ConfigError as error:
        problem = _problem(name, text)
        raise CommandError(f"{problem} {SEE_VARS.format(name=name)}\n({error})") from None

    ctx.store.set_override(key, text, changed_by=ctx.sender_name or ctx.sender, now=ctx.now)
    return _replies(SAVED.format(name=name), config, ctx, name)


def resettext(ctx: CommandContext, args: str) -> list[str]:
    words = args.split()
    if not words:
        raise CommandError(NO_NAME)
    name = _template_name(words[0])
    if len(words) > 1:
        raise CommandError(RESET_EXTRA)
    if not ctx.store.delete_override(template_key(name)):
        return [NOT_CHANGED.format(name=name)]
    config = effective_config(ctx.base, ctx.store, ctx.now)
    return _replies(RESET.format(name=name), config, ctx, name)


SETTEXT = Command(
    name="settext",
    usage="/settext <name>",
    summary="Ändert einen Text; der neue Text kommt in die Zeilen darunter.",
    run=settext,
)
RESETTEXT = Command(
    name="resettext",
    usage="/resettext <name>",
    summary="Setzt einen Text auf den Standardtext zurück.",
    run=resettext,
)
