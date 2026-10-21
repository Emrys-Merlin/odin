"""Typed values exchanged with Signal."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Group:
    """A Signal group the bot belongs to or is invited to.

    ``id`` is the signal-cli-rest-api form (``group.<base64>``) used to send to the group;
    ``internal_id`` is the raw Signal group ID as it appears in incoming messages.
    ``member`` is false while the bot is only invited and has not joined yet.
    """

    id: str
    internal_id: str
    name: str
    member: bool = True


@dataclass(frozen=True, slots=True)
class ApiInfo:
    """What ``GET /v1/about`` says about signal-cli-rest-api; ODIN needs ``mode == "json-rpc"``."""

    mode: str
    version: str


@dataclass(frozen=True, slots=True)
class DirectMessage:
    """A text message sent to the bot directly (not in a group).

    ``sender`` is the phone number, or the UUID if the sender hides their number;
    ``sender_uuid`` is the UUID (ACI) if Signal gave one, so a sender can be recognised by either.
    ``sender_name`` is their Signal profile name, if known.
    """

    sender: str
    text: str
    timestamp: int
    sender_uuid: str | None = None
    sender_name: str | None = None


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


@dataclass(frozen=True, slots=True)
class GroupMessage:
    """A text message someone wrote in a group the bot is in.

    ``sender`` is the phone number, or the UUID if the sender hides their number (as for
    ``ReactionEvent.reactor``); ``sender_name`` is their Signal profile name, if known.
    ``group_id`` is the ``group.<base64>`` form, ``timestamp`` the sent time (ms since epoch).
    """

    sender: str
    sender_name: str | None
    text: str
    group_id: str
    timestamp: int


type Event = ReactionEvent | GroupMessage | DirectMessage
