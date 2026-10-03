"""The interface the bot uses to talk to Signal."""

from collections.abc import AsyncIterator
from typing import Protocol

from odib.signal.models import Event, Group


class SignalClient(Protocol):
    """What the bot needs from Signal. Group IDs are in ``group.<base64>`` form."""

    async def send_group_message(self, group_id: str, text: str) -> int:
        """Send ``text`` to a group and return the sent message's timestamp (ms)."""
        ...

    async def list_groups(self) -> list[Group]:
        """List the groups the bot account is a member of."""
        ...

    def events(self) -> AsyncIterator[Event]:
        """Stream incoming events. Events the bot does not care about are not yielded."""
        ...
