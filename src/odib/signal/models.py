"""Typed values exchanged with Signal."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Group:
    """A Signal group the bot is a member of.

    ``id`` is the signal-cli-rest-api form (``group.<base64>``) used to send to the group;
    ``internal_id`` is the raw Signal group ID as it appears in incoming messages.
    """

    id: str
    internal_id: str
    name: str


@dataclass(frozen=True, slots=True)
class ReactionEvent:
    """Someone added or removed an emoji reaction on a group message.

    Signal identifies a message by its author and its sent timestamp (ms since epoch), so the
    reacted-to message is given by ``target_author`` + ``target_timestamp``.
    """

    emoji: str
    reactor: str
    target_author: str
    target_timestamp: int
    group_id: str
    is_remove: bool
    timestamp: int


type Event = ReactionEvent
