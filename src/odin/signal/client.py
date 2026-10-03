"""The interface the bot uses to talk to Signal."""

from collections.abc import AsyncIterator
from typing import Protocol

from odin.signal.models import ApiInfo, DirectMessage, Event, Group


class SignalClient(Protocol):
    """What the bot needs from Signal. Group IDs are in ``group.<base64>`` form."""

    async def send_group_message(self, group_id: str, text: str) -> int:
        """Send ``text`` to a group and return the sent message's timestamp (ms)."""
        ...

    async def list_groups(self) -> list[Group]:
        """List the groups the bot account is in or invited to (see ``Group.member``)."""
        ...

    def events(self) -> AsyncIterator[Event]:
        """Stream incoming events. Events the bot does not care about are not yielded."""
        ...


class SignalAdmin(Protocol):
    """Account administration for the setup wizard; the running bot never needs it.

    Failed calls raise a :class:`odin.signal.errors.SignalApiError` subclass.

    Behaviour of signal-cli-rest-api (json-rpc mode) to keep in mind:

    - Every received message is fanned out to *all* WebSocket clients of the number, without
      blocking: a client not ready at that moment misses it. The bot and the wizard would both
      see a direct message, so the setup lock stays the safe default.
    - An already registered account cannot be registered again (``AlreadyRegistered``): the
      REST API does not pass signal-cli's ``reregister`` flag.
    - The running daemon picks up a newly verified account; no restart is needed.
    """

    number: str

    async def about(self) -> ApiInfo:
        """Mode and version of the Signal API."""
        ...

    async def list_accounts(self) -> list[str]:
        """The numbers registered with the Signal API."""
        ...

    async def register(self, captcha: str | None = None, use_voice: bool = False) -> None:
        """Request a verification code by SMS (or voice call) for ``number``."""
        ...

    async def verify(self, code: str, pin: str | None = None) -> None:
        """Finish the registration with the received code (and the PIN if the number has one)."""
        ...

    async def set_pin(self, pin: str) -> None:
        """Set the registration lock PIN."""
        ...

    async def update_profile(self, name: str, avatar: bytes | None = None) -> None:
        """Set the profile name and, if given, the avatar image."""
        ...

    async def send_direct_message(self, recipient: str, text: str) -> int:
        """Send ``text`` to one number and return the sent message's timestamp (ms)."""
        ...

    async def list_groups(self) -> list[Group]:
        """List the groups the account is a member of or invited to."""
        ...

    def direct_messages(self) -> AsyncIterator[DirectMessage]:
        """Stream incoming direct text messages; everything else is not yielded."""
        ...
