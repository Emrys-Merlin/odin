"""/hiatus and /resume: put the weekly cycle to sleep until someone wakes it up again.

`/hiatus` itself only records the request (who, when, `Store.request_hiatus`). ODIN replies with
what it would post to the dinner group and asks for the configured emoji (👍) on that reply; the
reply is tracked as the week's hiatus request (see `TrackedReply`). Once anyone in the flat group
reacts, the engine lets the hiatus take effect on its next tick (`odin.engine.start_hiatus`): if
the running week's flat ask went out, it first cancels that week exactly as `/cancel` does; then
it posts the hiatus notice, once. The request lapses when the week's dinner starts.

`/resume` ends the hiatus at once; it posts nothing, and needs no confirmation. The first week
whose flat ask is still ahead runs normally (`odin.engine.hiatus_end`).
"""

from datetime import UTC, date, datetime

from odin.commands import ui
from odin.commands.core import Command, CommandContext, CommandError, TrackedReply
from odin.config import WEEKDAYS_DE, Config
from odin.cycle import TemplateName
from odin.engine import dinner_week, hiatus_end
from odin.store import Action, MessageKind, Outcome, Store

USAGE = "So geht's: einfach /hiatus, ohne Zusatz."
RESUME_USAGE = "So geht's: einfach /resume, ohne Zusatz."
CONFIRM = (
    "Odin in Pause schicken? Dann reagiert mit {emoji} auf diese Nachricht. Bis jemand /resume "
    "schreibt, frage ich die WG nicht mehr und schicke der Essensgruppe nichts – außer einmal, "
    "was unten steht."
)
CANCELS = (
    "Die Frage zum Essen am {day} ist schon raus – das sage ich vorher ab, genau wie mit /cancel."
)
NOTHING_TO_DINNER = (
    "Die Essensgruppe hat die Absage für das Essen am {day} schon; mehr schicke ich ihr nicht."
)
NO_TEXT = "Es gibt noch keinen eigenen Text für die Pause; /settext hiatus legt einen an."
TO_DINNER = "Das geht an die Essensgruppe:"
ALREADY = "Ich mache schon Pause, seit {at} (von {by}). " + ui.RESUME_HINT
ALREADY_REQUESTED = (
    "Die Pause ist schon angefragt ({at}) – reagiert mit {emoji} auf meine Nachricht von da."
)
NOT_ON_HIATUS = "Ich mache gerade keine Pause – es läuft alles wie gewohnt."
OPEN_REQUEST = (
    "Die angefragte Pause beginnt erst, wenn jemand mit {emoji} auf meine Nachricht dazu "
    "reagiert; ohne {emoji} verfällt sie, wenn das Essen beginnt ({dinner})."
)
RESUMED = "Pause beendet ✅ Ab jetzt läuft alles wieder wie gewohnt."
STILL_OFF = (
    "Für das Essen am {day} war die Frage an die WG schon fällig – das fällt noch aus, ohne "
    "Nachricht an die Essensgruppe."
)
NEXT = "/status zeigt, was als Nächstes kommt."


def run_hiatus(ctx: CommandContext, args: str) -> list[str]:
    if args:
        raise CommandError(USAGE)
    config, store = ctx.config, ctx.store
    active = store.active_hiatus()
    if active is not None:
        assert active.started_at is not None
        at = _local(config, active.started_at)
        raise CommandError(ALREADY.format(at=at, by=active.requested_by))
    week = dinner_week(config, ctx.now)
    request = store.tracked_message(week, MessageKind.HIATUS_REQUEST)
    if request is not None:
        requested_at = datetime.fromtimestamp(request.timestamp / 1000, UTC)
        raise CommandError(
            ALREADY_REQUESTED.format(at=_local(config, requested_at), emoji=config.emoji)
        )

    day = _day(week)
    lines = [CONFIRM.format(emoji=config.emoji)]
    cancels = _cancels(store, week)
    if cancels:
        lines.append(CANCELS.format(day=day))
    dinner = config.when(config.schedule.dinner, week)
    lines.append(ui.LAPSES.format(emoji=config.emoji, dinner=_local(config, dinner)))
    texts = _dinner_texts(config, store, week, cancels)
    if not config.templates.is_set(TemplateName.HIATUS):
        lines.append(NO_TEXT)
    if texts:
        body = "\n".join([*lines, "", TO_DINNER]) + "\n\n" + "\n\n".join(texts)
    else:
        body = "\n".join([*lines, NOTHING_TO_DINNER.format(day=day)])
    store.request_hiatus(week, ctx.sender_name or ctx.sender, ctx.now)
    return [TrackedReply(body, week, MessageKind.HIATUS_REQUEST)]


def run_resume(ctx: CommandContext, args: str) -> list[str]:
    if args:
        raise CommandError(RESUME_USAGE)
    config, store = ctx.config, ctx.store
    active = store.active_hiatus()
    week = dinner_week(config, ctx.now)
    if active is None:
        lines = [NOT_ON_HIATUS]
        if store.tracked_message(week, MessageKind.HIATUS_REQUEST) is not None:
            dinner = config.when(config.schedule.dinner, week)
            lines.append(OPEN_REQUEST.format(emoji=config.emoji, dinner=_local(config, dinner)))
        raise CommandError("\n".join(lines))
    until = hiatus_end(config, store, ctx.now)
    store.resume_hiatus(active.id, ctx.sender_name or ctx.sender, ctx.now, until)
    lines = [RESUMED]
    if until == week and active.from_day is not None and active.from_day <= week:
        lines.append(STILL_OFF.format(day=_day(week)))
    lines.append(NEXT)
    return ["\n".join(lines)]


def _cancels(store: Store, week: date) -> bool:
    """Whether the hiatus would cancel the running week: its flat ask went out, and its
    cancellation is not recorded yet (as in `odin.engine.start_hiatus`)."""
    return store.action_outcome(week, Action.FLAT_ASK) is Outcome.SENT and not store.has_action(
        week, Action.CANCELLATION
    )


def _dinner_texts(config: Config, store: Store, week: date, cancels: bool) -> list[str]:
    """What the dinner group would get, in order: the cancellation, then the hiatus notice —
    unless the notice is the cancellation (its template is not set) and the week has that."""
    values = config.placeholder_values()
    cancellation = config.templates.cancellation.render(**values)
    texts = [cancellation] if cancels else []
    cancelled = cancels or store.action_outcome(week, Action.CANCELLATION) is Outcome.SENT
    if config.templates.is_set(TemplateName.HIATUS) or not cancelled:
        texts.append(config.templates.get(TemplateName.HIATUS).render(**values))
    return texts


def _local(config: Config, moment: datetime) -> str:
    return ui.moment(moment, config.timezone)


def _day(week: date) -> str:
    return f"{WEEKDAYS_DE[week.weekday()]}, {week:%d.%m.}"


HIATUS = Command(
    name="hiatus",
    usage="/hiatus",
    summary="Schickt Odin in Pause, bis jemand /resume schreibt – nach Bestätigung per Reaktion.",
    run=run_hiatus,
)
RESUME = Command(
    name="resume",
    usage="/resume",
    summary="Beendet die Pause; ab der nächsten Frage an die WG läuft alles wie gewohnt.",
    run=run_resume,
)
