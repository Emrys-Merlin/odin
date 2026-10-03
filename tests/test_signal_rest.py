import asyncio
import json
from pathlib import Path

import httpx
import pytest

from odib.signal import Group, RestSignalClient, SignalClient

FIXTURES = Path(__file__).parent / "fixtures" / "signal"
NUMBER = "+4915100000001"


def make_client(handler, base_url: str = "http://signal-api:8080") -> RestSignalClient:
    return RestSignalClient(
        base_url, NUMBER, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def test_satisfies_protocol() -> None:
    client: SignalClient = make_client(lambda request: httpx.Response(500))
    assert client


def test_send_group_message() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, text=(FIXTURES / "send_response.json").read_text())

    client = make_client(handler)
    timestamp = asyncio.run(client.send_group_message("group.abc=", "Hallo 🍽️"))

    assert timestamp == 1760454000000
    [request] = requests
    assert request.method == "POST"
    assert str(request.url) == "http://signal-api:8080/v2/send"
    assert json.loads(request.content) == {
        "message": "Hallo 🍽️",
        "number": NUMBER,
        "recipients": ["group.abc="],
    }


def test_send_error_raises() -> None:
    client = make_client(lambda request: httpx.Response(400, json={"error": "bad"}))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.send_group_message("group.abc=", "x"))


def test_list_groups() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=(FIXTURES / "groups.json").read_text())

    groups = asyncio.run(make_client(handler, "http://signal-api:8080/").list_groups())

    assert requests[0].method == "GET"
    assert requests[0].url.path == f"/v1/groups/{NUMBER}"
    assert groups[1] == Group(
        id="group.WlVmSUhvSFlTV2V5NzQ0V0lFNE5RTkFOUmFIUkd1TFFmT0xXNUNXT1BKOD0=",
        internal_id="ZUfIHoHYSWey744WIE4NQNANRaHRGuLQfOLW5CWOPJ8=",
        name="Sonntagsessen",
    )


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("http://signal-api:8080", f"ws://signal-api:8080/v1/receive/{NUMBER}"),
        ("https://example.org/signal/", f"wss://example.org/signal/v1/receive/{NUMBER}"),
    ],
)
def test_receive_url(base_url: str, expected: str) -> None:
    assert make_client(lambda request: httpx.Response(500), base_url).receive_url == expected
