import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from odib.signal import (
    AlreadyRegistered,
    ApiInfo,
    DirectMessage,
    Event,
    Group,
    ReactionEvent,
    RestSignalClient,
    SignalAdmin,
    SignalApiError,
    SignalClient,
    VoiceRequired,
    rest,
)

FIXTURES = Path(__file__).parent / "fixtures" / "signal"
NUMBER = "+4915100000001"


def make_client(handler, base_url: str = "http://signal-api:8080") -> RestSignalClient:
    return RestSignalClient(
        base_url, NUMBER, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def test_satisfies_protocol() -> None:
    client: SignalClient = make_client(lambda request: httpx.Response(500))
    admin: SignalAdmin = make_client(lambda request: httpx.Response(500))
    assert client
    assert admin


class Recorder:
    """An httpx handler answering every request with one response, keeping the requests."""

    def __init__(self, status: int = 200, body: object = None) -> None:
        self.status = status
        self.body = body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.body is None:
            return httpx.Response(self.status)
        return httpx.Response(self.status, json=self.body)

    @property
    def request(self) -> httpx.Request:
        [request] = self.requests
        return request

    @property
    def body_sent(self) -> object:
        return json.loads(self.request.content) if self.request.content else None


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
        member=True,
    )
    assert groups[2].member is False


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("http://signal-api:8080", f"ws://signal-api:8080/v1/receive/{NUMBER}"),
        ("https://example.org/signal/", f"wss://example.org/signal/v1/receive/{NUMBER}"),
    ],
)
def test_receive_url(base_url: str, expected: str) -> None:
    assert make_client(lambda request: httpx.Response(500), base_url).receive_url == expected


def fixture_json(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def test_about() -> None:
    recorder = Recorder(200, fixture_json("about.json"))
    info = asyncio.run(make_client(recorder).about())
    assert info == ApiInfo(mode="json-rpc", version="0.97")
    assert recorder.request.method == "GET"
    assert str(recorder.request.url) == "http://signal-api:8080/v1/about"


def test_list_accounts() -> None:
    recorder = Recorder(200, fixture_json("accounts.json"))
    assert asyncio.run(make_client(recorder).list_accounts()) == ["+4915100000001"]
    assert recorder.request.method == "GET"
    assert str(recorder.request.url) == "http://signal-api:8080/v1/accounts"


def test_register_with_captcha() -> None:
    recorder = Recorder(201)
    asyncio.run(make_client(recorder).register("signalcaptcha://token", use_voice=True))
    assert recorder.request.method == "POST"
    assert recorder.request.url.path == f"/v1/register/{NUMBER}"
    assert recorder.body_sent == {"captcha": "signalcaptcha://token", "use_voice": True}


def test_register_without_captcha() -> None:
    recorder = Recorder(201)
    asyncio.run(make_client(recorder).register())
    assert recorder.body_sent == {"use_voice": False}


def test_verify_without_pin_sends_no_body() -> None:
    recorder = Recorder(201)
    asyncio.run(make_client(recorder).verify("123456"))
    assert recorder.request.method == "POST"
    assert recorder.request.url.path == f"/v1/register/{NUMBER}/verify/123456"
    assert recorder.body_sent is None


def test_verify_with_pin() -> None:
    recorder = Recorder(201)
    asyncio.run(make_client(recorder).verify("123456", pin="4711"))
    assert recorder.body_sent == {"pin": "4711"}


def test_set_pin() -> None:
    recorder = Recorder(201)
    asyncio.run(make_client(recorder).set_pin("4711"))
    assert recorder.request.method == "POST"
    assert recorder.request.url.path == f"/v1/accounts/{NUMBER}/pin"
    assert recorder.body_sent == {"pin": "4711"}


def test_update_profile_with_avatar() -> None:
    recorder = Recorder(204)
    asyncio.run(make_client(recorder).update_profile("Odin 🍽️", b"\x89PNG"))
    assert recorder.request.method == "PUT"
    assert recorder.request.url.path == f"/v1/profiles/{NUMBER}"
    assert recorder.body_sent == {"name": "Odin 🍽️", "base64_avatar": "iVBORw=="}


def test_update_profile_without_avatar() -> None:
    recorder = Recorder(204)
    asyncio.run(make_client(recorder).update_profile("Odin 🍽️"))
    assert recorder.body_sent == {"name": "Odin 🍽️"}


def test_send_direct_message() -> None:
    recorder = Recorder(201, fixture_json("send_response.json"))
    timestamp = asyncio.run(make_client(recorder).send_direct_message("+4915100000002", "Hallo"))
    assert timestamp == 1760454000000
    assert recorder.request.method == "POST"
    assert str(recorder.request.url) == "http://signal-api:8080/v2/send"
    assert recorder.body_sent == {
        "message": "Hallo",
        "number": NUMBER,
        "recipients": ["+4915100000002"],
    }


def test_admin_errors_are_mapped() -> None:
    message = (
        "Couldn't use SMS verification to register the specified number. "
        'Wait 60 seconds and try again with {"use_voice": true}'
    )
    client = make_client(Recorder(400, {"error": message}))
    with pytest.raises(VoiceRequired) as excinfo:
        asyncio.run(client.register("token"))
    assert excinfo.value.message == message

    client = make_client(Recorder(400, {"error": "Account is already registered"}))
    with pytest.raises(AlreadyRegistered):
        asyncio.run(client.register("token"))

    client = make_client(Recorder(500, {"error": "boom"}))
    with pytest.raises(SignalApiError) as generic:
        asyncio.run(client.send_direct_message("+4915100000002", "x"))
    assert (generic.value.status, generic.value.message) == (500, "boom")


def receive_with(monkeypatch: pytest.MonkeyPatch, messages: list[str]) -> list[str]:
    """Replace websockets.connect() by one connection that yields ``messages``, then ends.

    Returns the list the connected URLs are appended to.
    """
    urls: list[str] = []

    async def socket() -> AsyncIterator[str]:
        for message in messages:
            yield message

    async def connect(url: str) -> AsyncIterator[AsyncIterator[str]]:
        urls.append(url)
        yield socket()

    monkeypatch.setattr(rest.websockets, "connect", connect)
    return urls


def test_events_and_direct_messages_share_the_receive_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = [
        (FIXTURES / name).read_text()
        for name in ("direct_message.json", "reaction_add.json", "receipt.json")
    ]
    messages.insert(1, "{not json")
    urls = receive_with(monkeypatch, messages)
    client = make_client(lambda request: httpx.Response(500))

    async def collect() -> tuple[list[Event], list[DirectMessage]]:
        events = [event async for event in client.events()]
        dms = [dm async for dm in client.direct_messages()]
        return events, dms

    events, dms = asyncio.run(collect())
    assert [type(event) for event in events] == [ReactionEvent]
    assert dms == [
        DirectMessage(sender="+4915100000002", text="Ja, das bin ich.", timestamp=1760454500000)
    ]
    assert urls == [f"ws://signal-api:8080/v1/receive/{NUMBER}"] * 2
