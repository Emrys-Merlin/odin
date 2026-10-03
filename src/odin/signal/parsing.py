"""Turn signal-cli-rest-api JSON into typed values. Pure functions, no I/O."""

import base64
import json
from typing import Any

from odin.signal.models import ApiInfo, DirectMessage, Event, Group, ReactionEvent


def group_id_from_internal(internal_id: str) -> str:
    """Convert a raw Signal group ID to the ``group.<base64>`` form the REST API sends to.

    signal-cli-rest-api derives its group ID by base64-encoding the internal ID string.
    """
    return "group." + base64.b64encode(internal_id.encode()).decode()


def parse_event(raw: str | bytes) -> Event | None:
    """Parse one WebSocket message from ``/v1/receive/{number}``.

    Accepts both the bare ``{"envelope": ..., "account": ...}`` object that the REST API
    forwards in json-rpc mode and the full JSON-RPC ``receive`` notification wrapping it.
    Returns ``None`` for anything that is not a group reaction. Raises ``ValueError`` if
    ``raw`` is not valid JSON.
    """
    envelope = _envelope(raw)
    data_message = _dict(envelope.get("dataMessage"))
    reaction = _dict(data_message.get("reaction"))
    group_info = _dict(data_message.get("groupInfo"))
    if not reaction or not group_info:
        return None

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


def parse_direct_message(raw: str | bytes) -> DirectMessage | None:
    """Parse one WebSocket message from ``/v1/receive/{number}`` as a direct text message.

    A direct message is a ``dataMessage`` with text and without ``groupInfo`` and without
    ``reaction``. Returns ``None`` for anything else. Raises ``ValueError`` if ``raw`` is not
    valid JSON.
    """
    envelope = _envelope(raw)
    data_message = _dict(envelope.get("dataMessage"))
    if not data_message or "groupInfo" in data_message or "reaction" in data_message:
        return None

    text = data_message.get("message")
    sender = _author(envelope, "source")
    timestamp = envelope.get("timestamp")
    if not (isinstance(text, str) and text and sender and isinstance(timestamp, int)):
        return None
    return DirectMessage(sender=sender, text=text, timestamp=timestamp)


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
    """Parse the response of ``POST /v2/send``; the API returns the timestamp as a string."""
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
