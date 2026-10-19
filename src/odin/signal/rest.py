"""SignalClient and SignalAdmin backed by bbernhard/signal-cli-rest-api with ``MODE=json-rpc``."""

import base64
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import websockets

from odin.signal.errors import SendResponseUnreadable, raise_for_api_error
from odin.signal.models import ApiInfo, DirectMessage, Event, Group
from odin.signal.parsing import (
    parse_about,
    parse_accounts,
    parse_direct_message,
    parse_event,
    parse_groups,
    parse_send_timestamp,
)

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(30)
# signal-cli answers ``/v2/send`` only once the message went out to every member, so it may take
# longer than other calls. A send that times out while waiting for the answer may have been posted
# all the same and is retried (at least once, see `odin.engine`); the longer read timeout keeps
# that rare.
SEND_TIMEOUT = httpx.Timeout(30, read=120)


class RestSignalClient:
    """Talks REST for sending, listing and administration, WebSocket for receiving."""

    def __init__(
        self, base_url: str, number: str, http_client: httpx.AsyncClient | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.number = number
        self._http = http_client or httpx.AsyncClient(timeout=TIMEOUT)

    async def send_group_message(self, group_id: str, text: str) -> int:
        return await self._send(group_id, text)

    async def list_groups(self) -> list[Group]:
        return parse_groups(await self._request("GET", f"/v1/groups/{self.number}"))

    def events(self) -> AsyncIterator[Event]:
        return self._receive(parse_event)

    # SignalAdmin

    async def about(self) -> ApiInfo:
        return parse_about(await self._request("GET", "/v1/about"))

    async def list_accounts(self) -> list[str]:
        return parse_accounts(await self._request("GET", "/v1/accounts"))

    async def register(self, captcha: str | None = None, use_voice: bool = False) -> None:
        body: dict[str, Any] = {"use_voice": use_voice}
        if captcha is not None:
            body["captcha"] = captcha
        await self._request("POST", f"/v1/register/{self.number}", json=body)

    async def verify(self, code: str, pin: str | None = None) -> None:
        body = {"pin": pin} if pin is not None else None
        await self._request("POST", f"/v1/register/{self.number}/verify/{code}", json=body)

    async def set_pin(self, pin: str) -> None:
        await self._request("POST", f"/v1/accounts/{self.number}/pin", json={"pin": pin})

    async def update_profile(
        self, name: str, avatar: bytes | None = None, about: str | None = None
    ) -> None:
        body = {"name": name}
        if avatar is not None:
            body["base64_avatar"] = base64.b64encode(avatar).decode()
        if about is not None:
            body["about"] = about
        await self._request("PUT", f"/v1/profiles/{self.number}", json=body)

    async def send_direct_message(self, recipient: str, text: str) -> int:
        return await self._send(recipient, text)

    def direct_messages(self) -> AsyncIterator[DirectMessage]:
        return self._receive(parse_direct_message)

    @property
    def receive_url(self) -> str:
        ws_base = self.base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        return f"{ws_base}/v1/receive/{self.number}"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _send(self, recipient: str, text: str) -> int:
        """Send ``text`` to ``recipient`` (a number or a group ID); return its timestamp.

        Raises the mapped SignalApiError if the API refused the send, and SendResponseUnreadable
        if it accepted it but the response has no readable timestamp.
        """
        response = await self._call(
            "POST",
            "/v2/send",
            json={"message": text, "number": self.number, "recipients": [recipient]},
            timeout=SEND_TIMEOUT,
        )
        try:
            return parse_send_timestamp(response.json())
        except ValueError, KeyError, IndexError, TypeError:
            raise SendResponseUnreadable(response.text) from None

    async def _request(self, method: str, path: str, json: object = None) -> Any:
        """Send a request; raise the mapped SignalApiError on failure, else return the JSON."""
        response = await self._call(method, path, json=json)
        return response.json() if response.content else None

    async def _call(
        self, method: str, path: str, json: object = None, timeout: httpx.Timeout | None = None
    ) -> httpx.Response:
        """Send a request; raise the mapped SignalApiError on failure, else return the response."""
        response = await self._http.request(
            method,
            f"{self.base_url}{path}",
            json=json,
            timeout=timeout or httpx.USE_CLIENT_DEFAULT,
        )
        raise_for_api_error(response)
        return response

    async def _receive[T](self, parse: Callable[[str | bytes], T | None]) -> AsyncIterator[T]:
        """Yield what ``parse`` makes of each WebSocket message, skipping ``None``."""
        # Iterating over connect() reconnects with exponential backoff whenever the
        # connection drops or cannot be established.
        async for ws in websockets.connect(self.receive_url):
            try:
                async for raw in ws:
                    try:
                        item = parse(raw)
                    except ValueError:
                        logger.warning("Ignoring malformed message from Signal API: %r", raw)
                        continue
                    if item is not None:
                        yield item
            except websockets.ConnectionClosed:
                logger.warning("Signal API WebSocket closed, reconnecting")
