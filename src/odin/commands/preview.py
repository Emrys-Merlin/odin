"""Rendered previews of the weekly templates, shared by /text and /settext."""

from datetime import datetime

from odin.config import Config, dropped_placeholder_values
from odin.cycle import TemplateName
from odin.engine import dinner_week
from odin.reactions import count_confirmations
from odin.store import MessageKind, Store

SAMPLE_COUNT = 3


def render_preview(
    config: Config, store: Store, name: TemplateName, now: datetime
) -> tuple[str, bool]:
    """Template `name` (one of `EDITABLE_TEMPLATES`) rendered with this week's values.

    For ``tally``, ``{count}`` is the current confirmation count on the dinner announcement of
    the dinner week of `now`, or `SAMPLE_COUNT` if there is none. For
    ``weekday_change_cancellation``, the dates are those of the dinner week of `now` if it is
    dropped, else samples: the next dinner as the dropped one. Returns the text and whether
    sample values were used.
    """
    values: dict[str, object] = dict(config.placeholder_values())
    is_sample = False
    week = dinner_week(config, now)
    if name is TemplateName.TALLY:
        announcement = store.tracked_message(week, MessageKind.DINNER_ANNOUNCEMENT)
        if announcement is None:
            values["count"], is_sample = SAMPLE_COUNT, True
        else:
            values["count"] = count_confirmations(store, announcement, config.emoji)
    elif name is TemplateName.WEEKDAY_CHANGE_CANCELLATION:
        is_sample = store.dropped_at(week) is None
        values.update(dropped_placeholder_values(week))
    return config.templates.get(name).render(**values), is_sample
