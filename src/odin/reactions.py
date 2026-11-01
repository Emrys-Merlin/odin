"""Reaction tracking: turn incoming reaction events into stored reactions, and count them.

Only reactions on a tracked message (flat poll, dinner announcement) are stored. Every emoji is
stored — one reaction per reactor, a new one replaces the old — and counting filters on the
message's emojis: those in effect when it was sent (`TrackedMessage.emoji`), else the configured
ones. So "👍 by mistake, then removed" and "👍 switched to ❤️" both withdraw the vote.

On the dinner announcement, the cook emoji (🍳 by default) means "I'm coming and I'll help cook":
Signal allows one reaction per person, so it counts as coming too (`count_guests`). Everywhere
else only the plain emoji confirms (`count_confirmations`).

On the flat poll, reactions sent at or after the flat deadline are ignored (adding as well as
removing), so the vote the decision was based on stays as it was. Whether a reaction is late is
judged by its Signal timestamp — when the reactor sent it — not by when ODIN received it: a
reaction sent in time but delivered late (ODIN was down over the deadline) still counts for the
catch-up decision. The dinner announcement and the `/cancel` request have no deadline (the engine
ignores a request once its week's dinner has started). A flat poll of a week under an earlier
dinner weekday is long decided, so all reactions on it are ignored. An `/introduce` request
lapses `INTRODUCTION_LAPSE` after it was sent: reactions from then on are ignored.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from odin.config import Config, plain_emoji
from odin.signal import ReactionEvent
from odin.store import MessageKind, Store, TrackedMessage

logger = logging.getLogger(__name__)

# How long an `/introduce` request can be confirmed, from when ODIN sent it.
INTRODUCTION_LAPSE = timedelta(hours=24)


def reaction_deadline(config: Config, message: TrackedMessage) -> datetime | None:
    """From when on reactions on ``message`` are ignored; None if they never are."""
    if message.kind is MessageKind.INTRODUCTION_REQUEST:
        return datetime.fromtimestamp(message.timestamp / 1000, UTC) + INTRODUCTION_LAPSE
    if message.kind is not MessageKind.FLAT_POLL:
        return None
    if message.week.weekday() != config.schedule.dinner.weekday:
        # A week under an earlier dinner weekday: over before the new weekday took effect.
        return datetime.min.replace(tzinfo=UTC)
    return config.when(config.schedule.flat_deadline, message.week)


def handle_reaction(
    event: ReactionEvent, store: Store, config: Config, received_at: datetime
) -> bool:
    """Apply a reaction event to the store. Returns whether it was applied (not ignored)."""
    message = store.find_message(event.target_author, event.target_timestamp)
    if message is None:
        logger.debug("ignoring reaction on untracked message %s", event.target_timestamp)
        return False
    if event.group_id != message.group_id:
        logger.warning("ignoring reaction on %s from another group", message.kind)
        return False

    deadline = reaction_deadline(config, message)
    sent_at = datetime.fromtimestamp(event.timestamp / 1000, UTC)
    if deadline is not None and sent_at >= deadline:
        logger.info("ignoring reaction on %s sent after the deadline", message.kind)
        return False

    if event.is_remove:
        store.remove_reaction(message, event.reactor, event.emoji)
    else:
        store.set_reaction(message, event.reactor, event.emoji, received_at)
    return True


def same_emoji(a: str, b: str) -> bool:
    """Whether two emojis are the same, ignoring skin tone and variation selector."""
    return plain_emoji(a) == plain_emoji(b)


def confirm_emoji(message: TrackedMessage, config: Config) -> str:
    """The emoji that confirms ``message`` (or says "I'm coming" on the announcement)."""
    return message.emoji or config.emoji


def cook_emoji(message: TrackedMessage, config: Config) -> str:
    """The emoji that says "I'm coming and I'll help cook" on the announcement ``message``."""
    return message.cook_emoji or config.cook_emoji


def count_confirmations(store: Store, message: TrackedMessage, config: Config) -> int:
    """Number of distinct people currently confirming ``message`` with its emoji.

    Skin-tone variants count as the plain emoji.
    """
    emoji = confirm_emoji(message, config)
    return sum(1 for r in store.reactions_for(message) if same_emoji(r.emoji, emoji))


@dataclass(frozen=True, slots=True)
class Guests:
    """The reactions on a dinner announcement."""

    count: int  # people coming: the plain emoji or the cook emoji
    cooks: int  # of them, people helping cook: the cook emoji


NO_GUESTS = Guests(0, 0)


def count_guests(store: Store, announcement: TrackedMessage, config: Config) -> Guests:
    """Who is coming to dinner, by the reactions on ``announcement``."""
    emoji = confirm_emoji(announcement, config)
    cook = cook_emoji(announcement, config)
    coming = cooks = 0
    for reaction in store.reactions_for(announcement):
        if same_emoji(reaction.emoji, cook):
            coming, cooks = coming + 1, cooks + 1
        elif same_emoji(reaction.emoji, emoji):
            coming += 1
    return Guests(coming, cooks)
