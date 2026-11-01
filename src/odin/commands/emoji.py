"""/emoji: show and change the two reaction emojis.

- ``attend`` (`Config.emoji`, 👍 by default) — "I'm coming" on the dinner announcement; it also
  confirms the flat poll and the requests of `/cancel`, `/hiatus` and `/introduce`.
- ``cook`` (`Config.cook_emoji`, 🍳 by default) — "I'm coming and I'll help cook" on the dinner
  announcement. Signal allows one reaction per person, so it counts as coming too.

A change is stored as the override `EMOJI_KEY` / `COOK_EMOJI_KEY`; `reset` drops it, back to the
config file. It applies from ODIN's next message on: a tracked message keeps counting the emojis
it was sent with (`odin.store.TrackedMessage.emoji`), since its text asked for those.
"""

from odin.commands import ui
from odin.commands.core import Command, CommandContext, CommandError
from odin.config import Config, ConfigError, check_emojis, parse_emoji
from odin.overrides import COOK_EMOJI_KEY, EMOJI_KEY, apply_overrides, current_values

USAGE = (
    "So geht's: /emoji zeigt die Reaktionen; /emoji attend <emoji> oder /emoji cook <emoji> "
    "ändert eine, z. B. /emoji cook 🧑‍🍳; /emoji reset [attend|cook] setzt zurück."
)
HEADLINE = "Reaktionen:"
LINES = {
    EMOJI_KEY: "attend: {emoji} – „ich komme“ auf der Einladung; bestätigt auch die Frage an die "
    "WG und Anfragen wie /cancel",
    COOK_EMOJI_KEY: "cook: {emoji} – „ich komme und helfe beim Kochen“ auf der Einladung "
    "(zählt auch als Zusage)",
}
FROM_NEXT_MESSAGE = (
    "Das gilt ab meiner nächsten Nachricht. Was schon rausgegangen ist, zählt weiter die "
    "Reaktionen, nach denen es gefragt hat."
)
NOT_AN_EMOJI = "{value} ist kein einzelnes Emoji – bitte genau ein Emoji, z. B. /emoji cook 🧑‍🍳."
SAME_AS_OTHER = (
    "{value} ist schon die andere Reaktion ({name}: {other}) – die beiden müssen sich "
    "unterscheiden, sonst kann ich Kommen und Mitkochen nicht auseinanderhalten."
)
NOT_OVERRIDDEN = "Die Reaktionen waren nicht geändert – sie sind wie in der Config."
RESET_CONFLICT = (
    "Zurücksetzen geht nicht: In der Config ist {name} {value}, und das ist gerade die andere "
    "Reaktion. Ändere erst die andere mit /emoji."
)

_KEYS = {"attend": EMOJI_KEY, "cook": COOK_EMOJI_KEY}
_FIELDS = {EMOJI_KEY: "emoji", COOK_EMOJI_KEY: "cook_emoji"}
_NAMES = {key: name for name, key in _KEYS.items()}


def run(ctx: CommandContext, args: str) -> list[str]:
    words = args.split()
    if not words:
        return [_show(ctx, ctx.config)]
    which = words[0].lower()
    if which == "reset" and len(words) <= 2:
        return [_reset(ctx, words[1].lower() if len(words) == 2 else None)]
    if which in _KEYS and len(words) == 2:
        return [_set(ctx, _KEYS[which], words[1])]
    raise CommandError(USAGE)


def _set(ctx: CommandContext, key: str, value: str) -> str:
    try:
        emoji = parse_emoji(value, key)
    except ConfigError:
        raise CommandError(NOT_AN_EMOJI.format(value=value)) from None
    other = _other(ctx.config, key)
    try:
        check_emojis(emoji, other)
    except ConfigError:
        name = _NAMES[COOK_EMOJI_KEY if key == EMOJI_KEY else EMOJI_KEY]
        raise CommandError(SAME_AS_OTHER.format(value=emoji, name=name, other=other)) from None
    ctx.store.set_override(key, emoji, ctx.sender_name or ctx.sender, ctx.now)
    updated = apply_overrides(ctx.base, current_values(ctx.store))
    return "\n".join([ui.SAVED, _show(ctx, updated), FROM_NEXT_MESSAGE])


def _reset(ctx: CommandContext, which: str | None) -> str:
    if which is not None and which not in _KEYS:
        raise CommandError(USAGE)
    keys = list(_KEYS.values()) if which is None else [_KEYS[which]]
    stored = current_values(ctx.store)
    dropped = [key for key in keys if key in stored]
    if not dropped:
        return NOT_OVERRIDDEN
    for key in dropped:
        del stored[key]
    try:
        updated = apply_overrides(ctx.base, stored)
    except ConfigError:
        # Back to the config file, the reset emoji would equal the other one, still overridden.
        key = dropped[0]
        value = getattr(ctx.base, _FIELDS[key])
        raise CommandError(RESET_CONFLICT.format(name=_NAMES[key], value=value)) from None
    for key in dropped:
        ctx.store.delete_override(key)
    return "\n".join([ui.RESET, _show(ctx, updated), FROM_NEXT_MESSAGE])


def _show(ctx: CommandContext, config: Config) -> str:
    overrides = ctx.store.overrides()
    lines = [HEADLINE]
    for key, field in _FIELDS.items():
        line = LINES[key].format(emoji=getattr(config, field))
        override = overrides.get(key)
        if override is not None:
            marker = ui.override_marker(override.changed_by, override.changed_at, config.timezone)
            line += " " + marker
        lines.append(line)
    return "\n".join(lines)


def _other(config: Config, key: str) -> str:
    return config.cook_emoji if key == EMOJI_KEY else config.emoji


EMOJI = Command(
    name="emoji",
    usage="/emoji [attend|cook <emoji> | reset [attend|cook]]",
    summary="Zeigt oder ändert die Reaktionen fürs Kommen und fürs Mitkochen.",
    run=run,
    changes=True,
)
