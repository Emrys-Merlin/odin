import json
from pathlib import Path

import pytest

from odin.signal import (
    ApiInfo,
    DirectMessage,
    GroupMessage,
    ReactionEvent,
    group_id_from_internal,
    parse_direct_message,
    parse_event,
)
from odin.signal.parsing import parse_about, parse_accounts, parse_groups, parse_send_timestamp

FIXTURES = Path(__file__).parent / "fixtures" / "signal"
FLAT_GROUP_ID = "group.a0RVUHdhT295V3JUOHZNSjVtQi9zOEdjRndWdjhHeGUyakYzZTltSXVPMD0="


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_reaction_add() -> None:
    assert parse_event(fixture("reaction_add.json")) == ReactionEvent(
        emoji="👍",
        reactor="+4915100000002",
        target_author="+4915100000001",
        target_timestamp=1760454000000,
        group_id=FLAT_GROUP_ID,
        is_remove=False,
        timestamp=1760454123456,
    )


def test_reaction_remove_in_jsonrpc_envelope_with_hidden_number() -> None:
    assert parse_event(fixture("reaction_remove_jsonrpc.json")) == ReactionEvent(
        emoji="👍",
        reactor="5c6a3e2b-1f0d-4c8e-9a7b-2d3e4f5a6b7c",
        target_author="+4915100000001",
        target_timestamp=1760454000000,
        group_id=FLAT_GROUP_ID,
        is_remove=True,
        timestamp=1760454200000,
    )


def test_bytes_payload() -> None:
    assert parse_event(fixture("reaction_add.json").encode()) is not None


def test_group_message() -> None:
    assert parse_event(fixture("text_message.json")) == GroupMessage(
        sender="+4915100000002",
        sender_name="Alex",
        text="Ich bringe noch jemanden mit!",
        group_id=FLAT_GROUP_ID,
        timestamp=1760454300000,
    )


def test_group_reply_in_jsonrpc_envelope_with_hidden_number() -> None:
    assert parse_event(fixture("group_reply_jsonrpc.json")) == GroupMessage(
        sender="5c6a3e2b-1f0d-4c8e-9a7b-2d3e4f5a6b7c",
        sender_name="Alex",
        text="/status",
        group_id=FLAT_GROUP_ID,
        timestamp=1760454400000,
    )


@pytest.mark.parametrize("name", [None, ""])
def test_group_message_without_sender_name(name: str | None) -> None:
    data = json.loads(fixture("text_message.json"))
    data["envelope"]["sourceName"] = name
    message = parse_event(json.dumps(data))
    assert isinstance(message, GroupMessage)
    assert message.sender_name is None


@pytest.mark.parametrize(
    "name",
    ["receipt.json", "direct_reaction.json", "direct_message.json", "sync_message_jsonrpc.json"],
)
def test_non_group_events_are_ignored(name: str) -> None:
    assert parse_event(fixture(name)) is None


def test_attachment_only_group_message_is_ignored() -> None:
    data = json.loads(fixture("text_message.json"))
    data_message = data["envelope"]["dataMessage"]
    data_message["message"] = None
    data_message["attachments"] = [{"contentType": "image/jpeg", "id": "a1b2c3.jpg", "size": 1}]
    assert parse_event(json.dumps(data)) is None


def test_edited_group_message_is_ignored() -> None:
    data = json.loads(fixture("text_message.json"))
    data_message = data["envelope"].pop("dataMessage")
    data["envelope"]["editMessage"] = {
        "targetSentTimestamp": 1760454300000,
        "dataMessage": {**data_message, "message": "Ich bringe zwei Leute mit!"},
    }
    assert parse_event(json.dumps(data)) is None


def test_group_story_is_ignored() -> None:
    data = json.loads(fixture("text_message.json"))
    del data["envelope"]["dataMessage"]
    data["envelope"]["storyMessage"] = {
        "allowsReplies": True,
        "groupId": "kDUPwaOoyWrT8vMJ5mB/s8GcFwVv8Gxe2jF3e9mIuO0=",
        "textAttachment": {"text": "Sonntag!"},
    }
    assert parse_event(json.dumps(data)) is None


def test_group_message_missing_fields_is_ignored() -> None:
    data = json.loads(fixture("text_message.json"))
    del data["envelope"]["timestamp"]
    assert parse_event(json.dumps(data)) is None


@pytest.mark.parametrize("payload", ["[]", "null", '{"error": "boom"}', '{"envelope": 3}'])
def test_unexpected_shapes_are_ignored(payload: str) -> None:
    assert parse_event(payload) is None


def test_reaction_missing_fields_is_ignored() -> None:
    data = json.loads(fixture("reaction_add.json"))
    del data["envelope"]["dataMessage"]["reaction"]["targetSentTimestamp"]
    assert parse_event(json.dumps(data)) is None


def test_malformed_json_raises() -> None:
    with pytest.raises(ValueError):
        parse_event("{not json")


def test_group_id_from_internal_matches_api() -> None:
    for group in json.loads(fixture("groups.json")):
        assert group_id_from_internal(group["internal_id"]) == group["id"]


def test_parse_groups() -> None:
    groups = parse_groups(json.loads(fixture("groups.json")))
    assert [(g.name, g.id, g.member) for g in groups] == [
        ("WG", FLAT_GROUP_ID, True),
        (
            "Sonntagsessen",
            "group.WlVmSUhvSFlTV2V5NzQ0V0lFNE5RTkFOUmFIUkd1TFFmT0xXNUNXT1BKOD0=",
            True,
        ),
        (
            "Buchclub",
            "group.UW05dmF6TkRiSFZpU1c1MmFYUmxaRWR5YjNWd1NXUkdiM0pQWkdsdU1UST0=",
            False,
        ),
    ]
    assert groups[0].internal_id == "kDUPwaOoyWrT8vMJ5mB/s8GcFwVv8Gxe2jF3e9mIuO0="


def test_parse_send_timestamp() -> None:
    assert parse_send_timestamp(json.loads(fixture("send_response.json"))) == 1760454000000


def test_parse_send_timestamp_from_list() -> None:
    # signal-cli-rest-api returns one response per recipient batch since 6a225e6 (2026-07).
    assert parse_send_timestamp(json.loads(fixture("send_response_list.json"))) == 1760454000000


def test_parse_groups_without_member_field_counts_as_member() -> None:
    data = json.loads(fixture("groups.json"))
    for item in data:
        del item["member"]
    assert all(group.member for group in parse_groups(data))


def test_direct_message() -> None:
    assert parse_direct_message(fixture("direct_message.json")) == DirectMessage(
        sender="+4915100000002", text="Ja, das bin ich.", timestamp=1760454500000
    )


def test_direct_message_in_jsonrpc_envelope_with_hidden_number() -> None:
    data = json.loads(fixture("direct_message.json"))
    data["envelope"]["sourceNumber"] = None
    data["envelope"]["source"] = data["envelope"]["sourceUuid"]
    wrapped = {"jsonrpc": "2.0", "method": "receive", "params": data}
    message = parse_direct_message(json.dumps(wrapped).encode())
    assert message is not None
    assert message.sender == "5c6a3e2b-1f0d-4c8e-9a7b-2d3e4f5a6b7c"


@pytest.mark.parametrize(
    "name",
    [
        "text_message.json",
        "group_reply_jsonrpc.json",
        "sync_message_jsonrpc.json",
        "receipt.json",
        "direct_reaction.json",
        "reaction_add.json",
        "reaction_remove_jsonrpc.json",
    ],
)
def test_non_direct_messages_are_ignored(name: str) -> None:
    assert parse_direct_message(fixture(name)) is None


def test_direct_message_without_text_is_ignored() -> None:
    data = json.loads(fixture("direct_message.json"))
    data["envelope"]["dataMessage"]["message"] = None
    assert parse_direct_message(json.dumps(data)) is None


@pytest.mark.parametrize("payload", ["[]", "null", '{"error": "boom"}', '{"envelope": 3}'])
def test_direct_message_unexpected_shapes_are_ignored(payload: str) -> None:
    assert parse_direct_message(payload) is None


def test_direct_message_malformed_json_raises() -> None:
    with pytest.raises(ValueError):
        parse_direct_message("{not json")


def test_parse_about() -> None:
    assert parse_about(json.loads(fixture("about.json"))) == ApiInfo(
        mode="json-rpc", version="0.97"
    )


def test_parse_accounts() -> None:
    assert parse_accounts(json.loads(fixture("accounts.json"))) == ["+4915100000001"]
