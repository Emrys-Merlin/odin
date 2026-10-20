"""Whether ODIN can do its job, for monitors to ask: the state behind `GET /health`.

The reconcile loop, `serve` and the event connection record what they see in a `HealthState`;
`check` turns it into the answer, as a pure function of (state, now). Answering never calls the
Signal API, so polling adds no load and no new way to fail.

ODIN is **down** while any of these holds:

- **starting** — the bot has not finished its first reconcile tick yet, or `serve` has not yet
  found out whether ODIN is ready;
- **not ready** — `serve` waits (not set up, `odin setup` running, number not registered, Signal
  API unreachable);
- **stale loop** — no reconcile tick has finished for more than `STALE_TICKS` × the tick
  interval, and no tick is in progress for less than that (a send may take a while);
- **unsent step** — a step has failed to send for more than `UNSENT_LIMIT`, counted from its
  first failed attempt;
- **event connection down** — the WebSocket to the Signal API has not been up since the bot
  started, or has been down for more than `RECONNECT_GRACE`, so reactions are missed.

A tracked message whose reactions cannot be counted (see `odin.notices`) is only a **warning**:
the flat group is told already, the operator need not act.

The answer holds no personal data: step names, dates, durations and error classes only — the
health port may be reachable by more people than the chats are.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import odin
from odin.clock import Clock
from odin.engine import SendFailure
from odin.store import Action, MessageKind, Outcome, Store

# A step that keeps failing for this long is reported; a single failed tick is not.
UNSENT_LIMIT = timedelta(minutes=15)
logger = logging.getLogger(__name__)

# A reconnect of the event WebSocket within this time is not reported.
RECONNECT_GRACE = timedelta(minutes=2)
# The loop is stale after this many tick intervals without a finished tick.
STALE_TICKS = 3

PATH = "/health"
# A request that is not complete by then is dropped.
REQUEST_TIMEOUT = timedelta(seconds=5)

STARTING = "starting"

# The tracked messages of a week whose reactions count, and the action that sends each.
_TRACKED = (
    (Action.FLAT_ASK, MessageKind.FLAT_POLL),
    (Action.ANNOUNCEMENT, MessageKind.DINNER_ANNOUNCEMENT),
)


@dataclass
class _Unsent:
    since: datetime  # the first failed attempt
    error: str


@dataclass
class HealthState:
    """What the bot has seen, as `check` needs it. Every method is told the time."""

    tick_interval: timedelta = timedelta(seconds=60)
    # Why `serve` waits; None while the bot runs. STARTING until `serve` knows.
    waiting: str | None = STARTING
    # Waiting only for `odin setup` (not set up, setup running, number not registered).
    setup_pending: bool = False
    bot_started: datetime | None = None
    last_tick: datetime | None = None  # the end of the last tick that did not raise
    tick_started: datetime | None = None  # a tick in progress
    connected: bool = False
    ever_connected: bool = False
    disconnected_since: datetime | None = None
    unsent: dict[tuple[date, Action], _Unsent] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def wait(self, reason: str, *, setup_pending: bool) -> None:
        """`serve` waits, for `reason`."""
        self.waiting = reason
        self.setup_pending = setup_pending
        self.bot_started = None

    def start_bot(self, now: datetime) -> None:
        """The bot starts: nothing it saw before counts any more."""
        self.waiting = None
        self.setup_pending = False
        self.bot_started = now
        self.last_tick = self.tick_started = None
        self.ever_connected = self.connected
        self.disconnected_since = None if self.connected else now
        self.unsent.clear()
        self.warnings = []

    def start_tick(self, now: datetime) -> None:
        self.tick_started = now

    def end_tick(
        self, now: datetime, failures: Iterable[SendFailure] | None, warnings: list[str]
    ) -> None:
        """A tick ended; `failures` are its failed sends, None if the tick raised.

        A step that failed before and is not among `failures` was sent, skipped or is no longer
        due, so it is forgotten.
        """
        self.tick_started = None
        if failures is None:
            return
        self.last_tick = now
        unsent = {}
        for failure in failures:
            key = (failure.week, failure.action)
            since = self.unsent[key].since if key in self.unsent else now
            unsent[key] = _Unsent(since, failure.error)
        self.unsent = unsent
        self.warnings = warnings

    def event_connection(self, connected: bool, now: datetime) -> None:
        """The WebSocket to the Signal API went up or down."""
        if connected:
            self.ever_connected = True
            self.disconnected_since = None
        elif self.connected or self.disconnected_since is None:
            self.disconnected_since = now
        self.connected = connected


@dataclass(frozen=True)
class Health:
    """The answer of `GET /health`."""

    reasons: list[str]
    warnings: list[str]
    setup_pending: bool

    @property
    def up(self) -> bool:
        return not self.reasons

    @property
    def status_code(self) -> int:
        return 200 if self.up else 503

    def body(self) -> dict[str, object]:
        return {
            "status": "up" if self.up else "down",
            "reasons": self.reasons,
            "warnings": self.warnings,
            "setup_pending": self.setup_pending,
            "version": odin.__version__,
        }


def check(state: HealthState, now: datetime) -> Health:
    """Whether ODIN is up at `now`, and if not, why."""
    if state.waiting is not None:
        reason = state.waiting if state.waiting == STARTING else f"not ready: {state.waiting}"
        return Health([reason], [], state.setup_pending)
    reasons: list[str] = []
    limit = STALE_TICKS * state.tick_interval
    if state.last_tick is None:
        assert state.bot_started is not None
        if now - state.bot_started > limit and not _ticking(state, now, limit):
            reasons.append(
                f"no reconcile tick finished since the bot started {_ago(state.bot_started, now)}"
            )
        else:
            reasons.append(STARTING)
    elif now - state.last_tick > limit and not _ticking(state, now, limit):
        reasons.append(f"last reconcile tick finished {_ago(state.last_tick, now)}")
    for (week, action), unsent in state.unsent.items():
        if now - unsent.since > UNSENT_LIMIT:
            reasons.append(
                f"{action} for week {week} unsent for {_minutes(now - unsent.since)}"
                f" ({unsent.error})"
            )
    if not state.connected:
        if not state.ever_connected:
            reasons.append("Signal event connection not up yet")
        elif (
            state.disconnected_since is not None
            and now - state.disconnected_since > RECONNECT_GRACE
        ):
            down = _minutes(now - state.disconnected_since)
            reasons.append(f"Signal event connection down for {down}")
    return Health(reasons, list(state.warnings), False)


def untracked_warnings(store: Store, week: date) -> list[str]:
    """Warnings for the messages of `week` that went out but whose reactions cannot be counted.

    Not for a cancelled week: it needs no reactions any more.
    """
    if store.action_outcome(week, Action.CANCELLATION) is Outcome.SENT:
        return []
    return [
        f"{action} for week {week} sent, but its reactions cannot be counted"
        for action, kind in _TRACKED
        if store.action_outcome(week, action) is Outcome.SENT
        and store.tracked_message(week, kind) is None
    ]


# --- HTTP ---------------------------------------------------------------------------------------

_REASONS = {
    200: "OK",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    503: "Service Unavailable",
}


@dataclass(frozen=True)
class Response:
    status: int
    body: dict[str, object]
    headers: tuple[tuple[str, str], ...] = ()

    def encode(self) -> bytes:
        content = json.dumps(self.body).encode()
        head = [
            f"HTTP/1.1 {self.status} {_REASONS[self.status]}",
            "Content-Type: application/json",
            f"Content-Length: {len(content)}",
            "Connection: close",
            *(f"{name}: {value}" for name, value in self.headers),
        ]
        return "\r\n".join(head).encode() + b"\r\n\r\n" + content


def respond(request: bytes, state: HealthState, now: datetime) -> Response:
    """The response to an HTTP request (its head: request line and headers).

    `GET /health` (any query string) answers with `check`; another path is 404, another method
    on it 405.
    """
    parts = request.split(b"\r\n", 1)[0].decode("latin-1").split()
    if len(parts) != 3 or not parts[2].startswith("HTTP/"):
        return Response(400, {"error": "bad request"})
    method, target = parts[0], parts[1]
    if target.split("?", 1)[0] != PATH:
        return Response(404, {"error": "not found"})
    if method != "GET":
        return Response(405, {"error": "method not allowed"}, (("Allow", "GET"),))
    health = check(state, now)
    return Response(health.status_code, health.body())


async def start_server(state: HealthState, clock: Clock, port: int) -> asyncio.Server:
    """Serve `GET /health` on all interfaces at `port`, until the returned server is closed."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT.total_seconds()):
                request = await reader.readuntil(b"\r\n\r\n")
                writer.write(respond(request, state, clock.now()).encode())
                await writer.drain()
        except TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, OSError:
            logger.debug("dropped an incomplete health request")
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    server = await asyncio.start_server(handle, port=port)
    logger.info("health endpoint on port %d, path %s", port, PATH)
    return server


def _ticking(state: HealthState, now: datetime, limit: timedelta) -> bool:
    return state.tick_started is not None and now - state.tick_started <= limit


def _ago(moment: datetime, now: datetime) -> str:
    return f"{_minutes(now - moment)} ago"


def _minutes(duration: timedelta) -> str:
    return f"{int(duration.total_seconds() // 60)} min"
