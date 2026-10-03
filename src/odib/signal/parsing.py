"""Turn signal-cli-rest-api JSON into typed values. Pure functions, no I/O."""

import base64
import json
from typing import Any

from odib.signal.models import Event, Group, ReactionEvent


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
    data = json.loads(raw)
    if not isinstance(data, dict):
        return None
    if data.get("method") == "receive" and isinstance(data.get("params"), dict):
        data = data["params"]

    envelope = _dict(data.get("envelope"))
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


def parse_groups(data: Any) -> list[Group]:
    """Parse the response of ``GET /v1/groups/{number}``."""
    return [
        Group(id=item["id"], internal_id=item["internal_id"], name=item.get("name") or "")
        for item in data
    ]


def parse_send_timestamp(data: Any) -> int:
    """Parse the response of ``POST /v2/send``; the API returns the timestamp as a string."""
    return int(data["timestamp"])


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _author(obj: dict[str, Any], prefix: str) -> str | None:
    """Prefer the phone number, fall back to the UUID (numbers can be hidden)."""
    for key in (f"{prefix}Number", f"{prefix}Uuid", prefix):
        value = obj.get(key)
        if isinstance(value, str) and value:
            return value
    return None
