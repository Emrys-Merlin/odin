"""/texts and /text <name>: show the weekly message templates."""

from odin.commands import ui
from odin.commands.core import Command, CommandContext, CommandError
from odin.commands.preview import SAMPLE_COUNT, render_preview
from odin.config import TEMPLATE_FALLBACKS
from odin.overrides import EDITABLE_TEMPLATES, template_key

FLAT = "WG-Gruppe"
DINNER = "Essensgruppe"

# Template name -> (group it goes to, German one-liner), in the order of the weekly cycle.
DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "flat_ask": (FLAT, "Frage, ob das Essen stattfindet"),
    "nudge": (FLAT, "Erinnerung, wenn noch niemand bestätigt hat"),
    "announcement": (DINNER, "Ankündigung mit Bitte um Rückmeldung"),
    "cancellation": (DINNER, "Absage"),
    "weekday_change_cancellation": (DINNER, "Absage beim Wechsel des Wochentags"),
    "tally": (FLAT, "Anzahl der Zusagen zum Bestellen"),
}

TEXTS_INTRO = "Texte:"
TEXTS_HINT = "Anzeigen: /text <name>"
VALID_NAMES = "Möglich: " + ", ".join(EDITABLE_TEMPLATES)
MISSING_NAME = "Welcher Text? " + VALID_NAMES + "\nZ. B. /text announcement"
UNKNOWN_NAME = "Unbekannter Text „{name}“. " + VALID_NAMES
PREVIEW = "Vorschau (diese Woche):"
PREVIEW_COUNT = "Vorschau (diese Woche, aktuelle Zahl der Zusagen):"
PREVIEW_SAMPLE = f"Vorschau (diese Woche, noch keine Ankündigung – Beispielzahl {SAMPLE_COUNT}):"
PREVIEW_SAMPLE_DATES = "Vorschau (Beispiel: als fiele das nächste Essen aus):"
# An optional template without a text of its own, in /texts and /text.
FALLBACK = "nicht gesetzt, es gilt {fallback}"


def _marker(ctx: CommandContext, name: str) -> str | None:
    """The override marker of template `name`, or None if it comes from the config file."""
    override = ctx.store.overrides().get(template_key(name))
    if override is None:
        return None
    return ui.override_marker(override.changed_by, override.changed_at, ctx.config.timezone)


def _with_marker(text: str, marker: str | None) -> str:
    return text if marker is None else f"{text} {marker}"


def _fallback(ctx: CommandContext, name: str) -> str | None:
    """The note on an optional template that uses its fallback's text, else None."""
    if ctx.config.templates.is_set(name):
        return None
    return FALLBACK.format(fallback=TEMPLATE_FALLBACKS[name])


def run_texts(ctx: CommandContext, args: str) -> list[str]:
    lines = []
    for name in EDITABLE_TEMPLATES:
        group, description = DESCRIPTIONS[name]
        line = f"{name} ({group}) – {description}"
        fallback = _fallback(ctx, name)
        if fallback is not None:
            line += f" ({fallback})"
        lines.append(_with_marker(line, _marker(ctx, name)))
    return ["\n".join([TEXTS_INTRO, *lines, "", TEXTS_HINT])]


def run_text(ctx: CommandContext, args: str) -> list[str]:
    """Two replies: the raw template as a ready-to-send /settext command, and a preview."""
    if not args:
        raise CommandError(MISSING_NAME)
    name = args.lower()
    if name not in EDITABLE_TEMPLATES:
        raise CommandError(UNKNOWN_NAME.format(name=args))
    raw = ctx.config.templates.get(name).text
    preview, is_sample = render_preview(ctx.config, ctx.store, name, ctx.now)
    header = PREVIEW
    if name == "tally":
        header = PREVIEW_SAMPLE if is_sample else PREVIEW_COUNT
    elif is_sample:
        header = PREVIEW_SAMPLE_DATES
    fallback = _fallback(ctx, name)
    if fallback is not None:
        header = f"{header.removesuffix(':')} ({fallback}):"
    return [f"/settext {name}\n{raw}", f"{_with_marker(header, _marker(ctx, name))}\n{preview}"]


TEXTS = Command(name="texts", usage="/texts", summary="Listet die änderbaren Texte.", run=run_texts)
TEXT = Command(
    name="text",
    usage="/text <name>",
    summary="Zeigt einen Text zum Kopieren und als Vorschau.",
    run=run_text,
)
