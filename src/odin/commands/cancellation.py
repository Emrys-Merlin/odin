"""/cancellation on|off|reset: whether the dinner group is told when dinner does not take place.

Switches `decision.cancellation` via the override `CANCELLATION_ENABLED_KEY`; `reset` drops the
override, back to the config file's value. Off, the cancellation is not posted by itself — no
confirmation, a skip date, a dropped week or a hiatus without a template of their own — but a
`/cancel` still posts it (see `odin.engine.cancellation_silenced`). A change applies to the running
week as long as its decision is not recorded.
"""

from odin.commands.core import Command, CommandContext, CommandError
from odin.commands.ui import FROM_NEXT_WEEK, RESET, SAVED, THIS_WEEK
from odin.engine import dinner_week
from odin.overrides import (
    CANCELLATION_ENABLED_KEY,
    apply_overrides,
    current_values,
    format_bool,
)
from odin.store import Action

USAGE = "So geht's: /cancellation on, /cancellation off oder /cancellation reset."
STATE_LINE = "Absage an die Essensgruppe (cancellation): {state}"
ON = "an"
OFF = "aus"
OFF_NOTE = (
    "Ohne {emoji} fällt das Essen weiterhin aus, aber die Essensgruppe bekommt keine Absage – "
    "auch nicht per /skip, beim Wechsel des Essenstags oder bei einer Pause ohne eigenen Text. "
    "/cancel schickt die Absage trotzdem."
)
NOT_OVERRIDDEN = "Die Absage an die Essensgruppe war nicht geändert – sie ist {state}."

_ARGS = {"on": True, "off": False}


def run(ctx: CommandContext, args: str) -> list[str]:
    words = args.lower().split()
    if len(words) != 1 or words[0] not in {*_ARGS, "reset"}:
        raise CommandError(USAGE)
    stored = current_values(ctx.store)
    if words[0] == "reset":
        if CANCELLATION_ENABLED_KEY not in stored:
            return [NOT_OVERRIDDEN.format(state=_state(ctx.config.decision.cancellation))]
        del stored[CANCELLATION_ENABLED_KEY]
        enabled = apply_overrides(ctx.base, stored).decision.cancellation
        ctx.store.delete_override(CANCELLATION_ENABLED_KEY)
        return [_reply(ctx, RESET, enabled)]
    enabled = _ARGS[words[0]]
    ctx.store.set_override(
        CANCELLATION_ENABLED_KEY, format_bool(enabled), ctx.sender_name or ctx.sender, ctx.now
    )
    return [_reply(ctx, SAVED, enabled)]


def _reply(ctx: CommandContext, headline: str, enabled: bool) -> str:
    lines = [headline, STATE_LINE.format(state=_state(enabled))]
    if not enabled:
        lines.append(OFF_NOTE.format(emoji=ctx.config.emoji))
    lines.append(THIS_WEEK if _decision_ahead(ctx) else FROM_NEXT_WEEK)
    return "\n".join(lines)


def _decision_ahead(ctx: CommandContext) -> bool:
    """Whether the running week's decision is not recorded yet, so the change applies to it."""
    week = dinner_week(ctx.config, ctx.now)
    return not any(
        ctx.store.has_action(week, a) for a in (Action.ANNOUNCEMENT, Action.CANCELLATION)
    )


def _state(enabled: bool) -> str:
    return ON if enabled else OFF


CANCELLATION = Command(
    name="cancellation",
    usage="/cancellation on|off|reset",
    summary="Schaltet die Absage an die Essensgruppe an oder aus, wenn das Essen ausfällt.",
    run=run,
    changes=True,
)
