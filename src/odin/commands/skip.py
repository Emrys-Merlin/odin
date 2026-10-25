"""/skip and /unskip: dinner days without dinner, set in advance.

`/skip <JJJJ-MM-TT>` stores a dinner day as a skip date in the state DB (`Store.add_skip_date`),
`/skip` alone lists the upcoming ones, and `/unskip <JJJJ-MM-TT>` takes one back. In the dinner
week of a skip date ODIN does not ask the flat group and posts the cancellation to the dinner
group at the usual decision time (see `odin.engine`), unless the cancellation is switched off.

Skipping the current week once it has started — its flat ask is recorded, it was dropped by a
dinner weekday change, or a /cancel request is open — is `/cancel`: `/skip` with that day replies
exactly as `/cancel` does. A skip date takes effect when its week's flat ask is due; from then on
`/unskip` is refused.

The day must be a dinner day of the schedule that runs then, a pending dinner weekday change
included. Skip dates can be entered during a hiatus (`/hiatus`); one that falls into the hiatus
gets no cancellation, one after a later `/resume` works as usual.
"""

import dataclasses
import re
from datetime import date

from odin.commands import cancel, ui
from odin.commands.core import Command, CommandContext, CommandError
from odin.config import WEEKDAYS_DE, Config
from odin.engine import cancellation_silenced, dinner_week
from odin.overrides import pending_dinner
from odin.store import MessageKind

USAGE = "So geht's: /skip JJJJ-MM-TT, z. B. /skip 2026-12-27 – oder /skip allein für die Liste."
UNSKIP_USAGE = "So geht's: /unskip JJJJ-MM-TT, z. B. /unskip 2026-12-27."
NO_SUCH_DATE = "Den {date} gibt es nicht."
NOT_A_DINNER_DAY = "Der {day} ist kein Essenstag – das Essen ist {weekdays}."
PAST = "Das Essen am {day} ist schon vorbei."
DROPPED_WEEK = "Das Essen am {day} fällt schon wegen des Wechsels des Essenstags aus."
ALREADY_SKIPPED = "Für {day} ist schon eingetragen, dass kein Essen ist ({marker})."
SKIPPED = (
    "Eingetragen: Am {day} gibt es kein Essen. Ich frage die WG in der Woche nicht und schicke "
    "der Essensgruppe am {at} diese Absage:"
)
SKIPPED_SILENTLY = (
    "Eingetragen: Am {day} gibt es kein Essen. Ich frage die WG in der Woche nicht. Die Absage an "
    "die Essensgruppe ist aus (/cancellation) – ist sie am {at} noch aus, bekommt die "
    "Essensgruppe nichts."
)
UNDO = "/unskip {iso} nimmt das zurück."
HIATUS = (
    "Ich mache gerade Pause: Fällt der Tag noch in die Pause, schicke ich auch diese Absage nicht."
)
LIST_HEADER = "Kein Essen an diesen Tagen:"
LIST_EMPTY = "Es sind keine Tage ohne Essen eingetragen."
NO_DINNER_DAY = "(kein Essenstag mehr)"
LIST_FOOTER = "Eintragen: /skip JJJJ-MM-TT · Zurücknehmen: /unskip JJJJ-MM-TT"
NOT_SKIPPED = "Für {day} ist kein Tag ohne Essen eingetragen. /skip zeigt die Liste."
TOO_LATE = (
    "Zu spät: Die Frage an die WG für das Essen am {day} ist schon ausgefallen – "
    "das Essen bleibt abgesagt."
)
UNSKIPPED = "Zurückgenommen: Am {day} gibt es wieder Essen wie immer."

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def run_skip(ctx: CommandContext, args: str) -> list[str]:
    if not args:
        return [_list(ctx)]
    day = _parse(args, USAGE)
    store = ctx.store
    skip = store.skip_date(day)
    if skip is not None:
        marker = ui.override_marker(skip.added_by, skip.added_at, ctx.config.timezone)
        raise CommandError(ALREADY_SKIPPED.format(day=_day(day), marker=marker))
    if day == dinner_week(ctx.config, ctx.now) and (
        store.has_any_action(day)
        or store.dropped_at(day) is not None
        or store.tracked_message(day, MessageKind.CANCEL_REQUEST) is not None
    ):
        return cancel.run(ctx, "")
    config = _check_upcoming(ctx, day)
    store.add_skip_date(day, ctx.sender_name or ctx.sender, ctx.now)
    decision = config.when(config.schedule.flat_deadline, day)
    at = f"{ui.WEEKDAYS_SHORT[decision.weekday()]} {decision:%d.%m. %H:%M}"
    undo = UNDO.format(iso=day.isoformat())
    if cancellation_silenced(config):
        return [f"{SKIPPED_SILENTLY.format(day=_day(day), at=at)}\n\n{undo}"]
    cancellation = config.templates.cancellation.render(**config.placeholder_values())
    reply = SKIPPED.format(day=_day(day), at=at)
    if store.active_hiatus() is not None:
        undo = f"{HIATUS}\n{undo}"
    return [f"{reply}\n\n{cancellation}\n\n{undo}"]


def run_unskip(ctx: CommandContext, args: str) -> list[str]:
    day = _parse(args, UNSKIP_USAGE)
    if ctx.store.skip_date(day) is None:
        raise CommandError(NOT_SKIPPED.format(day=_day(day)))
    if day < dinner_week(ctx.config, ctx.now):
        raise CommandError(PAST.format(day=_day(day)))
    if ctx.store.has_any_action(day):
        raise CommandError(TOO_LATE.format(day=_day(day)))
    ctx.store.delete_skip_date(day)
    return [UNSKIPPED.format(day=_day(day))]


def _list(ctx: CommandContext) -> str:
    skips = ctx.store.skip_dates(since=dinner_week(ctx.config, ctx.now))
    if not skips:
        return f"{LIST_EMPTY}\n{LIST_FOOTER}"
    lines = [LIST_HEADER]
    for skip in skips:
        line = f"• {ui.short_date(skip.day)}"
        if _config_for(ctx, skip.day).schedule.dinner.weekday != skip.day.weekday():
            line += f" {NO_DINNER_DAY}"
        line += " " + ui.override_marker(skip.added_by, skip.added_at, ctx.config.timezone)
        lines.append(line)
    return "\n".join([*lines, "", LIST_FOOTER])


def _parse(args: str, usage: str) -> date:
    if not _DATE.fullmatch(args):
        raise CommandError(usage)
    try:
        return date.fromisoformat(args)
    except ValueError:
        raise CommandError(NO_SUCH_DATE.format(date=args)) from None


def _check_upcoming(ctx: CommandContext, day: date) -> Config:
    """The config dinner week `day` runs under; raises if `day` is no upcoming dinner day."""
    if day < dinner_week(ctx.config, ctx.now):
        raise CommandError(PAST.format(day=_day(day)))
    config = _config_for(ctx, day)
    dinner = config.schedule.dinner
    if day.weekday() != dinner.weekday:
        weekdays = WEEKDAYS_DE[dinner.weekday].lower() + "s"
        raise CommandError(NOT_A_DINNER_DAY.format(day=_day(day), weekdays=weekdays))
    pending = pending_dinner(ctx.base, ctx.store, ctx.now)
    if ctx.store.dropped_at(day) is not None or (
        pending is not None and pending.transition.dropped_week == day
    ):
        raise CommandError(DROPPED_WEEK.format(day=_day(day)))
    return config


def _config_for(ctx: CommandContext, day: date) -> Config:
    """The effective config, with the dinner of a pending weekday change if `day` is after it."""
    pending = pending_dinner(ctx.base, ctx.store, ctx.now)
    if pending is None or day <= pending.after_week:
        return ctx.config
    schedule = dataclasses.replace(ctx.config.schedule, dinner=pending.point)
    return dataclasses.replace(ctx.config, schedule=schedule)


def _day(day: date) -> str:
    """``Sonntag, 27.12.2026``."""
    return f"{WEEKDAYS_DE[day.weekday()]}, {day:%d.%m.%Y}"


SKIP = Command(
    name="skip",
    usage="/skip [JJJJ-MM-TT]",
    summary="Trägt einen Tag ohne Essen im Voraus ein; ohne Datum: zeigt die Liste.",
    run=run_skip,
    changes=True,
)
UNSKIP = Command(
    name="unskip",
    usage="/unskip <JJJJ-MM-TT>",
    summary="Nimmt einen mit /skip eingetragenen Tag zurück.",
    run=run_unskip,
    changes=True,
)
