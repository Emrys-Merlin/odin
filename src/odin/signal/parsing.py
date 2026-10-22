"""Turn signal-cli-rest-api JSON into typed values. Pure functions, no I/O."""

import base64
import json
from typing import Any

from odin.signal.models import ApiInfo, DirectMessage, Event, Group, GroupMessage, ReactionEvent


def group_id_from_internal(internal_id: str) -> str:
    """Convert a raw Signal group ID to the ``group.<base64>`` form the REST API sends to.

    signal-cli-rest-api derives its group ID by base64-encoding the internal ID string.
    """
    return "group." + base64.b64encode(internal_id.encode()).decode()


def parse_event(raw: str | bytes) -> Event | None:
    """Parse one WebSocket message from ``/v1/receive/{number}``.

    Accepts both the bare ``{"envelope": ..., "account": ...}`` object that the REST API
    forwards in json-rpc mode and the full JSON-RPC ``receive`` notification wrapping it.
    Returns a ``ReactionEvent`` for a group reaction, a ``GroupMessage`` for a group text
    message, a ``DirectMessage`` for a direct text message (see `parse_direct_message`) and
    ``None`` for anything else: direct reactions, ODIN's own sends seen from another device
    (``syncMessage``), edits (``editMessage``), stories and messages without text.
    Raises ``ValueError`` if ``raw`` is not valid JSON.
    """
    envelope = _envelope(raw)
    data_message = _dict(envelope.get("dataMessage"))
    group_info = _dict(data_message.get("groupInfo"))
    if not group_info:
        return _direct_message(envelope)
    reaction = _dict(data_message.get("reaction"))
    if reaction:
        return _reaction_event(envelope, reaction, group_info)
    if "reaction" in data_message:  # a malformed reaction, not a text message
        return None
    return _group_message(envelope, data_message, group_info)


def _reaction_event(
    envelope: dict[str, Any], reaction: dict[str, Any], group_info: dict[str, Any]
) -> ReactionEvent | None:
    emoji = reaction.get("emoji")
    reactor = _author(envelope, "source")
    target_author = _author(reaction, "targetAuthor")
    target_timestamp = reaction.get("targetSentTimestamp")
    internal_group_id = group_info.get("groupId")
    timestamp = envelope.get("timestamp")
    if not (
        isinstance(emoji, str)
        and reactor
        and target_author
        and isinstance(target_timestamp, int)
        and isinstance(internal_group_id, str)
        and isinstance(timestamp, int)
    ):
        return None

    return ReactionEvent(
        emoji=emoji,
        reactor=reactor,
        target_author=target_author,
        target_timestamp=target_timestamp,
        group_id=group_id_from_internal(internal_group_id),
        is_remove=bool(reaction.get("isRemove", False)),
        timestamp=timestamp,
    )


def _group_message(
    envelope: dict[str, Any], data_message: dict[str, Any], group_info: dict[str, Any]
) -> GroupMessage | None:
    text = data_message.get("message")
    sender = _author(envelope, "source")
    sender_name = envelope.get("sourceName")
    internal_group_id = group_info.get("groupId")
    timestamp = envelope.get("timestamp")
    if not (
        isinstance(text, str)
        and text
        and sender
        and isinstance(internal_group_id, str)
        and isinstance(timestamp, int)
    ):
        return None

    return GroupMessage(
        sender=sender,
        sender_name=sender_name if isinstance(sender_name, str) and sender_name else None,
        text=text,
        group_id=group_id_from_internal(internal_group_id),
        timestamp=timestamp,
    )


def parse_direct_message(raw: str | bytes) -> DirectMessage | None:
    """Parse one WebSocket message from ``/v1/receive/{number}`` as a direct text message.

    A direct message is a ``dataMessage`` with text and without ``groupInfo`` and without
    ``reaction``. Returns ``None`` for anything else. Raises ``ValueError`` if ``raw`` is not
    valid JSON.
    """
    return _direct_message(_envelope(raw))


def _direct_message(envelope: dict[str, Any]) -> DirectMessage | None:
    data_message = _dict(envelope.get("dataMessage"))
    if not data_message or "groupInfo" in data_message or "reaction" in data_message:
        return None

    text = data_message.get("message")
    sender = _author(envelope, "source")
    sender_uuid = envelope.get("sourceUuid")
    sender_name = envelope.get("sourceName")
    timestamp = envelope.get("timestamp")
    if not (isinstance(text, str) and text and sender and isinstance(timestamp, int)):
        return None
    return DirectMessage(
        sender=sender,
        text=text,
        timestamp=timestamp,
        sender_uuid=sender_uuid if isinstance(sender_uuid, str) and sender_uuid else None,
        sender_name=sender_name if isinstance(sender_name, str) and sender_name else None,
    )


def parse_groups(data: Any) -> list[Group]:
    """Parse the response of ``GET /v1/groups/{number}``.

    A missing ``member`` field (older API versions) counts as member.
    """
    return [
        Group(
            id=item["id"],
            internal_id=item["internal_id"],
            name=item.get("name") or "",
            member=bool(item.get("member", True)),
        )
        for item in data
    ]


def parse_about(data: Any) -> ApiInfo:
    """Parse the response of ``GET /v1/about``."""
    return ApiInfo(mode=str(data.get("mode") or ""), version=str(data.get("version") or ""))


def parse_accounts(data: Any) -> list[str]:
    """Parse the response of ``GET /v1/accounts``: the registered numbers."""
    return [item for item in data if isinstance(item, str)]


def parse_send_timestamp(data: Any) -> int:
    """Parse the response of ``POST /v2/send``; the API returns the timestamp as a string.

    Newer API versions return a list with one response per recipient batch; ODIN always sends
    to a single recipient, so the first entry carries the timestamp.
    """
    if isinstance(data, list):
        data = data[0]
    return int(data["timestamp"])


def _envelope(raw: str | bytes) -> dict[str, Any]:
    """The ``envelope`` of a receive message, bare or wrapped in a JSON-RPC notification."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        return {}
    if data.get("method") == "receive" and isinstance(data.get("params"), dict):
        data = data["params"]
    return _dict(data.get("envelope"))


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _author(obj: dict[str, Any], prefix: str) -> str | None:
    """Prefer the phone number, fall back to the UUID (numbers can be hidden)."""
    for key in (f"{prefix}Number", f"{prefix}Uuid", prefix):
        value = obj.get(key)
        if isinstance(value, str) and value:
            return value
    return None
