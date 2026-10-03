"""SignalClient backed by bbernhard/signal-cli-rest-api running with ``MODE=json-rpc``."""

import logging
from collections.abc import AsyncIterator

import httpx
import websockets

from odib.signal.models import Event, Group
from odib.signal.parsing import parse_event, parse_groups, parse_send_timestamp

logger = logging.getLogger(__name__)


class RestSignalClient:
    """Talks REST for sending and listing, WebSocket for receiving."""

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

    async def events(self) -> AsyncIterator[Event]:
        # Iterating over connect() reconnects with exponential backoff whenever the
        # connection drops or cannot be established.
        async for ws in websockets.connect(self.receive_url):
            try:
                async for raw in ws:
                    try:
                        event = parse_event(raw)
                    except ValueError:
                        logger.warning("Ignoring malformed message from Signal API: %r", raw)
                        continue
                    if event is not None:
                        yield event
            except websockets.ConnectionClosed:
                logger.warning("Signal API WebSocket closed, reconnecting")

    @property
    def receive_url(self) -> str:
        ws_base = self.base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        return f"{ws_base}/v1/receive/{self.number}"

    async def aclose(self) -> None:
        await self._http.aclose()
