"""/vars [name]: list the placeholders of the editable templates with meaning and current value.

The list is generated from `TEMPLATE_PLACEHOLDERS`, so a new placeholder shows up on its own once
it has a description in `DESCRIPTIONS` (a test enforces that every one has).
"""

from odin.commands.core import Command, CommandContext, CommandError
from odin.config import TEMPLATE_PLACEHOLDERS
from odin.overrides import EDITABLE_TEMPLATES

# Placeholder -> German description, in the order /vars lists them. A `_de` / `_en` pair shares
# one description and is shown on one line.
DESCRIPTIONS = {
    "emoji": "Reaktion zum Bestätigen",
    "flat_ask_day_de": "Frage an die WG (Wochentag)",
    "flat_ask_day_en": "Frage an die WG (Wochentag)",
    "deadline": "Entscheidung der WG (Uhrzeit)",
    "deadline_day_de": "Entscheidung der WG (Wochentag)",
    "deadline_day_en": "Entscheidung der WG (Wochentag)",
    "rsvp_by": "Zusagen bitte bis (Uhrzeit)",
    "rsvp_by_day_de": "Zusagen bitte bis (Wochentag)",
    "rsvp_by_day_en": "Zusagen bitte bis (Wochentag)",
    "cook_time": "Mitkochen (Uhrzeit)",
    "cook_day_de": "Mitkochen (Wochentag)",
    "cook_day_en": "Mitkochen (Wochentag)",
    "dinner_time": "Essen (Uhrzeit)",
    "dinner_day_de": "Essen (Wochentag)",
    "dinner_day_en": "Essen (Wochentag)",
    "count": "Anzahl Zusagen auf die Ankündigung",
    "dropped_date": "Datum des Essens, das beim Wechsel des Wochentags ausfällt",
    "first_date": "Datum des ersten Essens am neuen Wochentag",
}

HEADER_ALL = "Platzhalter für /settext:"
HEADER_ONE = "Platzhalter für {name}:"
BRACES_HINT = "{{ und }} schreiben für eine wörtliche Klammer."
ONE_TEMPLATE_HINT = "Nur für eine Vorlage: /vars <name>"
ONLY_IN = "nur in {names}"
VARIES = "je nach Nachricht"
UNKNOWN_TEMPLATE = "Unbekannte Vorlage „{name}“. Es gibt: {names}."


def _order(placeholder: str) -> tuple[int, str]:
    keys = list(DESCRIPTIONS)
    return (keys.index(placeholder) if placeholder in keys else len(keys), placeholder)


def _pair(name: str) -> str | None:
    """The other half of a ``_de`` / ``_en`` pair (``cook_day_de`` -> ``cook_day_en``)."""
    for own, other in (("_de", "_en"), ("_en", "_de")):
        if name.endswith(own):
            return name.removesuffix(own) + other
    return None


def _lines(ctx: CommandContext, placeholders: frozenset[str]) -> list[str]:
    values = ctx.config.placeholder_values()
    lines = []
    for name in sorted(placeholders, key=_order):
        description = DESCRIPTIONS.get(name, "")
        partner = _pair(name)
        paired = partner in placeholders and {name, partner} <= values.keys()
        if paired and name.endswith("_en"):
            continue  # shown on the line of its _de partner
        if paired:
            # {x_de} / {x_en} – …: Mittwoch / Wednesday
            lines.append(
                f"{{{name}}} / {{{partner}}} – {description}: {values[name]} / {values[partner]}"
            )
        elif name in values:
            lines.append(f"{{{name}}} – {description}: {values[name]}")
        else:  # message-specific, e.g. {count}: no fixed value
            allowed_in = [t for t in EDITABLE_TEMPLATES if name in TEMPLATE_PLACEHOLDERS[t]]
            where = (
                ONLY_IN.format(names=", ".join(allowed_in))
                if len(allowed_in) < len(EDITABLE_TEMPLATES)
                else VARIES
            )
            lines.append(f"{{{name}}} – {description} ({where})")
    return lines


def run(ctx: CommandContext, args: str) -> list[str]:
    if not args:
        placeholders = frozenset().union(*(TEMPLATE_PLACEHOLDERS[t] for t in EDITABLE_TEMPLATES))
        lines = [HEADER_ALL, *_lines(ctx, placeholders), "", BRACES_HINT, ONE_TEMPLATE_HINT]
        return ["\n".join(lines)]
    name = args.lower()
    if name not in EDITABLE_TEMPLATES:
        raise CommandError(UNKNOWN_TEMPLATE.format(name=args, names=", ".join(EDITABLE_TEMPLATES)))
    lines = [HEADER_ONE.format(name=name), *_lines(ctx, TEMPLATE_PLACEHOLDERS[name])]
    return ["\n".join([*lines, "", BRACES_HINT])]


VARS = Command(
    name="vars",
    usage="/vars [name]",
    summary="Zeigt die Platzhalter für Texte mit ihren aktuellen Werten.",
    run=run,
)
