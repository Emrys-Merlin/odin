"""Render a weekly template the way it would be sent this week, for command replies."""

from datetime import datetime

from odin.config import Config
from odin.engine import dinner_week
from odin.reactions import count_confirmations
from odin.store import MessageKind, Store


def render_preview(config: Config, store: Store, name: str, now: datetime) -> tuple[str, bool]:
    """Template `name` (one of `EDITABLE_TEMPLATES`) rendered with this week's values.

    For ``tally``, ``{count}`` is the current number of confirmations on the dinner announcement
    of the dinner week of `now`, or a sample count of 3 if that week has no announcement (yet).
    Returns the text and whether the sample count was used.
    """
    values: dict[str, object] = dict(config.placeholder_values())
    is_sample = False
    if name == "tally":
        week = dinner_week(config, now)
        announcement = store.tracked_message(week, MessageKind.DINNER_ANNOUNCEMENT)
        if announcement is None:
            values["count"] = 3
            is_sample = True
        else:
            values["count"] = count_confirmations(store, announcement, config.emoji)
    template = getattr(config.templates, name)
    return template.render(**values), is_sample
