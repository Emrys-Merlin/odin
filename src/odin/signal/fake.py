"""In-memory SignalClient and SignalAdmin for tests."""

import asyncio
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import cast

from odin.signal.models import ApiInfo, DirectMessage, Event, Group


@dataclass(frozen=True, slots=True)
class SentMessage:
    group_id: str
    text: str
    timestamp: int


@dataclass(frozen=True, slots=True)
class SentDirectMessage:
    recipient: str
    text: str
    timestamp: int


class FakeSignalClient:
    """Records sent messages and yields events that tests inject.

    Group messages go to ``sent``, direct messages to ``sent_direct``; both get strictly
    increasing timestamps (shared) starting at ``first_timestamp``.
    ``events()`` yields injected events in order and ends once ``close()`` is called and
    all earlier events are consumed; like the real client, it tells ``on_connection`` that its
    connection is up when it starts and down when it ends. ``fail_sends()`` makes the next group
    sends raise.
    """

    def __init__(
        self,
        number: str = "+490000000000",
        groups: list[Group] | None = None,
        first_timestamp: int = 1_000,
        on_connection: Callable[[bool], None] | None = None,
    ) -> None:
        self.number = number
        self.groups = list(groups or [])
        self.on_connection = on_connection
        self.sent: list[SentMessage] = []
        self.sent_direct: list[SentDirectMessage] = []
        self._next_timestamp = first_timestamp
        self._queue: asyncio.Queue[Event | None] = asyncio.Queue()
        self._send_failures: deque[tuple[BaseException, bool]] = deque()

    def fail_sends(self, error: BaseException, *, delivered: bool = False, times: int = 1) -> None:
        """Make the next ``times`` group sends raise ``error``.

        With ``delivered`` the message is posted (recorded in ``sent``) before ``error`` is
        raised, like a send whose response could not be read.
        """
        self._send_failures.extend([(error, delivered)] * times)

    async def send_group_message(self, group_id: str, text: str) -> int:
        failure = self._send_failures.popleft() if self._send_failures else None
        if failure is not None and not failure[1]:
            raise failure[0]
        timestamp = self._next_timestamp
        self._next_timestamp += 1
        self.sent.append(SentMessage(group_id=group_id, text=text, timestamp=timestamp))
        if failure is not None:
            raise failure[0]
        return timestamp

    async def send_direct_message(self, recipient: str, text: str) -> int:
        return self._send_direct(recipient, text)

    def _send_direct(self, recipient: str, text: str) -> int:
        timestamp = self._next_timestamp
        self._next_timestamp += 1
        self.sent_direct.append(SentDirectMessage(recipient, text, timestamp))
        return timestamp

    async def list_groups(self) -> list[Group]:
        return list(self.groups)

    async def events(self) -> AsyncIterator[Event]:
        if self.on_connection is not None:
            self.on_connection(True)
        try:
            while (event := await self._queue.get()) is not None:
                yield event
        finally:
            if self.on_connection is not None:
                self.on_connection(False)

    def inject(self, event: Event) -> None:
        self._queue.put_nowait(event)

    def close(self) -> None:
        self._queue.put_nowait(None)


@dataclass(frozen=True, slots=True)
class AdminCall:
    """One call to a :class:`FakeSignalAdmin` method, with its arguments by name."""

    method: str
    args: dict[str, object] = field(default_factory=dict)


class FakeSignalAdmin(FakeSignalClient):
    """A scriptable SignalAdmin (and SignalClient) for tests.

    Every admin call is recorded in ``calls``. ``script(method, *outcomes)`` queues outcomes
    for the next calls of ``method``: an exception instance is raised, anything else is
    returned. Without a queued outcome a call succeeds: ``register`` and ``set_pin`` do
    nothing, ``verify`` adds ``number`` to ``accounts``, and the getters return the current
    ``api_info``, ``accounts`` and ``groups`` (which tests may change between calls).
    ``inject_direct()`` feeds ``direct_messages()``, which ends after ``close()``.
    """

    def __init__(
        self,
        number: str = "+490000000000",
        groups: list[Group] | None = None,
        first_timestamp: int = 1_000,
        accounts: list[str] | None = None,
        api_info: ApiInfo | None = None,
    ) -> None:
        super().__init__(number=number, groups=groups, first_timestamp=first_timestamp)
        self.accounts = list(accounts or [])
        self.api_info = api_info or ApiInfo(mode="json-rpc", version="0.0-fake")
        self.calls: list[AdminCall] = []
        self.profile: tuple[str, bytes | None, str | None] | None = None
        self.pin: str | None = None
        self._outcomes: dict[str, deque[object]] = defaultdict(deque)
        self._direct_queue: asyncio.Queue[DirectMessage | None] = asyncio.Queue()

    def script(self, method: str, *outcomes: object) -> None:
        """Queue results (or exceptions to raise) for the next calls of ``method``."""
        if not callable(getattr(self, method, None)):
            raise ValueError(f"FakeSignalAdmin has no method {method!r}")
        self._outcomes[method].extend(outcomes)

    def calls_to(self, method: str) -> list[AdminCall]:
        return [call for call in self.calls if call.method == method]

    async def about(self) -> ApiInfo:
        return self._call("about", lambda: self.api_info)

    async def list_accounts(self) -> list[str]:
        return self._call("list_accounts", lambda: list(self.accounts))

    async def register(self, captcha: str | None = None, use_voice: bool = False) -> None:
        self._call("register", lambda: None, captcha=captcha, use_voice=use_voice)

    async def verify(self, code: str, pin: str | None = None) -> None:
        def succeed() -> None:
            if self.number not in self.accounts:
                self.accounts.append(self.number)

        self._call("verify", succeed, code=code, pin=pin)

    async def set_pin(self, pin: str) -> None:
        def succeed() -> None:
            self.pin = pin

        self._call("set_pin", succeed, pin=pin)

    async def update_profile(
        self, name: str, avatar: bytes | None = None, about: str | None = None
    ) -> None:
        def succeed() -> None:
            self.profile = (name, avatar, about)

        self._call("update_profile", succeed, name=name, avatar=avatar, about=about)

    async def send_direct_message(self, recipient: str, text: str) -> int:
        return self._call(
            "send_direct_message",
            lambda: self._send_direct(recipient, text),
            recipient=recipient,
            text=text,
        )

    async def list_groups(self) -> list[Group]:
        return self._call("list_groups", lambda: list(self.groups))

    async def direct_messages(self) -> AsyncIterator[DirectMessage]:
        while (message := await self._direct_queue.get()) is not None:
            yield message

    def inject_direct(self, message: DirectMessage) -> None:
        self._direct_queue.put_nowait(message)

    def close(self) -> None:
        super().close()
        self._direct_queue.put_nowait(None)

    def _call[T](self, method: str, default: Callable[[], T], **args: object) -> T:
        self.calls.append(AdminCall(method, args))
        if self._outcomes[method]:
            outcome = self._outcomes[method].popleft()
            if isinstance(outcome, BaseException):
                raise outcome
            return cast(T, outcome)
        return default()
