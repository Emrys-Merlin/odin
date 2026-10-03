"""SignalClient and SignalAdmin backed by bbernhard/signal-cli-rest-api with ``MODE=json-rpc``."""

import base64
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import websockets

from odin.signal.errors import raise_for_api_error
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


class RestSignalClient:
    """Talks REST for sending, listing and administration, WebSocket for receiving."""

    def __init__(
        self, base_url: str, number: str, http_client: httpx.AsyncClient | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.number = number
        self._http = http_client or httpx.AsyncClient(timeout=30)

    async def send_group_message(self, group_id: str, text: str) -> int:
        response = await self._http.post(
            f"{self.base_url}/v2/send",
            json={"message": text, "number": self.number, "recipients": [group_id]},
        )
        response.raise_for_status()
        return parse_send_timestamp(response.json())

    async def list_groups(self) -> list[Group]:
        response = await self._http.get(f"{self.base_url}/v1/groups/{self.number}")
        response.raise_for_status()
        return parse_groups(response.json())

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

    async def update_profile(self, name: str, avatar: bytes | None = None) -> None:
        body = {"name": name}
        if avatar is not None:
            body["base64_avatar"] = base64.b64encode(avatar).decode()
        await self._request("PUT", f"/v1/profiles/{self.number}", json=body)

    async def send_direct_message(self, recipient: str, text: str) -> int:
        data = await self._request(
            "POST",
            "/v2/send",
            json={"message": text, "number": self.number, "recipients": [recipient]},
        )
        return parse_send_timestamp(data)

    def direct_messages(self) -> AsyncIterator[DirectMessage]:
        return self._receive(parse_direct_message)

    @property
    def receive_url(self) -> str:
        ws_base = self.base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        return f"{ws_base}/v1/receive/{self.number}"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, json: object = None) -> Any:
        """Send a request; raise the mapped SignalApiError on failure, else return the JSON."""
        response = await self._http.request(method, f"{self.base_url}{path}", json=json)
        raise_for_api_error(response)
        return response.json() if response.content else None

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
