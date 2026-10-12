"""Rendered previews of the weekly templates, shared by /text and /settext."""

from datetime import datetime

from odin.config import Config
from odin.engine import dinner_week
from odin.reactions import count_confirmations
from odin.store import MessageKind, Store

SAMPLE_COUNT = 3


def render_preview(config: Config, store: Store, name: str, now: datetime) -> tuple[str, bool]:
    """Template `name` (one of `EDITABLE_TEMPLATES`) rendered with this week's values.

    For ``tally``, ``{count}`` is the current confirmation count on the dinner announcement of
    the dinner week of `now`, or `SAMPLE_COUNT` if there is none. Returns the text and whether
    that sample count was used.
    """
    values: dict[str, object] = dict(config.placeholder_values())
    is_sample = False
    if name == "tally":
        week = dinner_week(config, now)
        announcement = store.tracked_message(week, MessageKind.DINNER_ANNOUNCEMENT)
        if announcement is None:
            values["count"], is_sample = SAMPLE_COUNT, True
        else:
            values["count"] = count_confirmations(store, announcement, config.emoji)
    return getattr(config.templates, name).render(**values), is_sample
