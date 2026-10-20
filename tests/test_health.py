"""The health state, its check and the HTTP answer; no socket is opened."""

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from odin.app import API_UNREACHABLE, SETUP_RUNNING, run_bot, serve
from odin.clock import FixedClock
from odin.config import ConfigError, load_config, load_env
from odin.engine import Account, SendFailure, reconcile
from odin.health import (
    RECONNECT_GRACE,
    STARTING,
    UNSENT_LIMIT,
    HealthState,
    check,
    respond,
    untracked_warnings,
)
from odin.signal import FakeSignalAdmin, FakeSignalClient, SendResponseUnreadable
from odin.store import Action, MessageKind, Store

EXAMPLE = Path(__file__).parent.parent / "config.example.toml"
CONFIG = load_config(EXAMPLE)
ACCOUNT = Account(number="+491701234567", flat_group_id="group.flat=", dinner_group_id="group.d=")
ENV = {
    "SIGNAL_NUMBER": ACCOUNT.number,
    "FLAT_GROUP_ID": ACCOUNT.flat_group_id,
    "DINNER_GROUP_ID": ACCOUNT.dinner_group_id,
    "ODIN_CONFIG": str(EXAMPLE),
    "ODIN_DB": "/data/odin.db",
}
WEEK = date(2026, 10, 11)
T0 = datetime(2026, 10, 6, 16, 5, tzinfo=UTC)  # Tue 18:05 in Berlin: the flat ask is due
TICK = timedelta(seconds=60)
LIMIT = 3 * TICK


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def running(*, ticked: bool = True, connected: bool = True) -> HealthState:
    """A bot started at T0; with `ticked`, its first tick ended at T0."""
    state = HealthState(tick_interval=TICK)
    state.start_bot(T0)
    if connected:
        state.event_connection(True, T0)
    if ticked:
        state.start_tick(T0)
        state.end_tick(T0, [], [])
    return state


def failure(action: Action = Action.ANNOUNCEMENT, error: str = "SignalApiError") -> SendFailure:
    return SendFailure(WEEK, action, error)


# --- check --------------------------------------------------------------------------------------


def test_up_once_ticked_and_connected() -> None:
    health = check(running(), at(1))
    assert health.up
    assert health.status_code == 200
    assert health.body()["status"] == "up"
    assert health.body()["reasons"] == []


def test_down_while_serve_has_not_looked_yet() -> None:
    health = check(HealthState(), T0)
    assert health.status_code == 503
    assert health.reasons == [STARTING]


def test_down_before_the_first_tick() -> None:
    assert check(running(ticked=False), at(1)).reasons == [STARTING]


def test_not_ready_reports_the_reason_of_serve() -> None:
    state = running()
    state.wait(SETUP_RUNNING, setup_pending=True)
    health = check(state, at(1))
    assert health.reasons == ["not ready: odin setup is running"]
    assert health.setup_pending
    assert health.body()["setup_pending"] is True


def test_an_unreachable_api_is_not_pending_setup() -> None:
    state = HealthState()
    state.wait(API_UNREACHABLE, setup_pending=False)
    health = check(state, T0)
    assert health.reasons == ["not ready: the Signal API is not reachable"]
    assert not health.setup_pending


def test_stale_loop_after_three_tick_intervals() -> None:
    state = running()
    assert check(state, T0 + LIMIT).up
    assert check(state, T0 + LIMIT + timedelta(seconds=1)).reasons == [
        "last reconcile tick finished 3 min ago"
    ]


def test_a_tick_in_progress_is_not_stale_until_it_takes_too_long() -> None:
    state = running()
    state.start_tick(at(150))  # a slow send
    assert check(state, at(150) + LIMIT).up
    assert not check(state, at(150) + LIMIT + timedelta(seconds=1)).up


def test_a_tick_that_raises_does_not_count() -> None:
    state = running()
    state.start_tick(at(60))
    state.end_tick(at(61), None, [])
    assert not check(state, T0 + LIMIT + timedelta(seconds=1)).up


def test_stale_without_any_tick_since_the_start() -> None:
    state = running(ticked=False)
    assert check(state, T0 + LIMIT).reasons == [STARTING]
    assert check(state, T0 + LIMIT + timedelta(seconds=1)).reasons == [
        "no reconcile tick finished since the bot started 3 min ago"
    ]


def test_unsent_step_after_15_minutes_from_the_first_failure() -> None:
    state = running()
    for second in range(0, int(UNSENT_LIMIT.total_seconds()) + 60, 60):
        state.start_tick(at(second))
        state.end_tick(
            at(second), [failure(error="SignalApiError" if second else "TimeoutError")], []
        )
    assert check(state, T0 + UNSENT_LIMIT).up
    health = check(state, T0 + UNSENT_LIMIT + timedelta(seconds=1))
    # The error is the one of the latest attempt.
    assert health.reasons == ["announcement for week 2026-10-11 unsent for 15 min (SignalApiError)"]


def test_a_step_no_longer_failing_is_forgotten() -> None:
    state = running()
    state.end_tick(T0, [failure()], [])
    state.end_tick(at(60), [], [])  # sent, or skipped
    state.end_tick(at(120), [failure()], [])  # fails again: counts from now
    state.end_tick(at(120) + UNSENT_LIMIT, [failure()], [])
    assert check(state, at(120) + UNSENT_LIMIT).up


def test_unsent_steps_are_reported_each() -> None:
    state = running()
    state.end_tick(T0, [failure(Action.TALLY), failure(Action.ANNOUNCEMENT_NOTICE)], [])
    now = T0 + UNSENT_LIMIT + timedelta(minutes=1)
    state.end_tick(now, [failure(Action.TALLY), failure(Action.ANNOUNCEMENT_NOTICE)], [])
    assert check(state, now).reasons == [
        "tally for week 2026-10-11 unsent for 16 min (SignalApiError)",
        "announcement_notice for week 2026-10-11 unsent for 16 min (SignalApiError)",
    ]


def test_event_connection_not_up_yet() -> None:
    assert check(running(connected=False), at(1)).reasons == ["Signal event connection not up yet"]


def test_event_connection_down_after_the_grace() -> None:
    state = running()
    state.event_connection(False, at(10))
    state.event_connection(False, at(20))  # still down: counts from the first
    assert check(state, at(10) + RECONNECT_GRACE).up
    assert check(state, at(11) + RECONNECT_GRACE).reasons == [
        "Signal event connection down for 2 min"
    ]
    state.event_connection(True, at(200))
    state.end_tick(at(200), [], [])
    assert check(state, at(200)).up


def test_a_restarted_bot_forgets_what_the_last_one_saw() -> None:
    state = running()
    state.end_tick(T0, [failure()], ["some warning"])
    state.event_connection(False, at(1))
    state.start_bot(at(2))
    assert state.unsent == {}
    assert state.warnings == []
    assert check(state, at(2)).reasons == [STARTING, "Signal event connection not up yet"]


def test_warnings_leave_the_status_up() -> None:
    state = running()
    state.end_tick(at(1), [], ["announcement for week 2026-10-11 sent, but …"])
    health = check(state, at(1))
    assert health.up
    assert health.body()["warnings"] == ["announcement for week 2026-10-11 sent, but …"]


# --- untracked_warnings -------------------------------------------------------------------------


def test_untracked_warnings(store: Store) -> None:
    assert untracked_warnings(store, WEEK) == []
    store.record_action(WEEK, Action.FLAT_ASK, T0)
    store.record_action(WEEK, Action.ANNOUNCEMENT, T0)
    store.track_message(WEEK, MessageKind.DINNER_ANNOUNCEMENT, "group.d=", ACCOUNT.number, 1)
    assert untracked_warnings(store, WEEK) == [
        "flat_ask for week 2026-10-11 sent, but its reactions cannot be counted"
    ]
    store.track_message(WEEK, MessageKind.FLAT_POLL, "group.flat=", ACCOUNT.number, 2)  # retry
    assert untracked_warnings(store, WEEK) == []


def test_no_untracked_warning_for_a_cancelled_week(store: Store) -> None:
    store.record_action(WEEK, Action.FLAT_ASK, T0)
    store.record_action(WEEK, Action.CANCELLATION, T0)
    assert untracked_warnings(store, WEEK) == []


# --- HTTP ---------------------------------------------------------------------------------------


def request(line: str) -> bytes:
    return f"{line}\r\nHost: localhost\r\n\r\n".encode()


def test_get_health() -> None:
    response = respond(request("GET /health HTTP/1.1"), running(), at(1))
    assert response.status == 200
    assert response.body["status"] == "up"
    encoded = response.encode()
    head, body = encoded.split(b"\r\n\r\n", 1)
    assert head.startswith(b"HTTP/1.1 200 OK\r\n")
    assert b"Content-Type: application/json" in head
    assert f"Content-Length: {len(body)}".encode() in head
    assert json.loads(body)["status"] == "up"


def test_get_health_down_is_503() -> None:
    response = respond(request("GET /health?probe=kuma HTTP/1.1"), HealthState(), T0)
    assert response.status == 503
    assert response.encode().startswith(b"HTTP/1.1 503 Service Unavailable\r\n")
    assert response.body["reasons"] == [STARTING]


def test_other_paths_are_404() -> None:
    for line in ("GET / HTTP/1.1", "GET /healthz HTTP/1.1", "POST /metrics HTTP/1.1"):
        assert respond(request(line), running(), at(1)).status == 404


def test_other_methods_are_405() -> None:
    for method in ("POST", "HEAD", "DELETE"):
        response = respond(request(f"{method} /health HTTP/1.1"), running(), at(1))
        assert response.status == 405
        assert ("Allow", "GET") in response.headers
        assert b"\r\nAllow: GET" in response.encode()


def test_garbage_is_400() -> None:
    for raw in (b"\r\n\r\n", b"hello\r\n\r\n", b"GET /health\r\n\r\n", b"\xff\xfe /x y\r\n\r\n"):
        assert respond(raw, running(), at(1)).status == 400


def test_the_body_holds_no_personal_data(store: Store) -> None:
    state = running()
    store.record_action(WEEK, Action.ANNOUNCEMENT, T0)
    state.end_tick(T0, [failure()], untracked_warnings(store, WEEK))
    state.end_tick(T0 + UNSENT_LIMIT * 2, [failure()], untracked_warnings(store, WEEK))
    state.wait("no flat group chosen", setup_pending=True)
    for health in (check(state, T0), check(running(), at(1))):
        text = json.dumps(health.body())
        for secret in (ACCOUNT.number, ACCOUNT.flat_group_id, ACCOUNT.dinner_group_id):
            assert secret not in text


# --- wiring: engine, run_bot, serve -------------------------------------------------------------


def test_reconcile_reports_failed_sends(store: Store) -> None:
    client = FakeSignalClient(number=ACCOUNT.number)
    client.fail_sends(ConnectionError("down"))
    failures: list[SendFailure] = []
    asyncio.run(reconcile(CONFIG, store, client, ACCOUNT, T0, failures))
    assert failures == [SendFailure(WEEK, Action.FLAT_ASK, "ConnectionError")]
    assert not store.has_action(WEEK, Action.FLAT_ASK)


def test_run_bot_records_its_ticks_and_connection(store: Store) -> None:
    state = HealthState(tick_interval=TICK)
    client = FakeSignalClient(
        number=ACCOUNT.number, on_connection=lambda up: state.event_connection(up, T0)
    )
    # The flat ask and its retry go out, but neither can be tracked.
    client.fail_sends(SendResponseUnreadable("{}"), delivered=True, times=2)
    clock = FixedClock(T0)

    async def scenario() -> None:
        stop = asyncio.Event()
        bot = asyncio.create_task(run_bot(CONFIG, store, client, ACCOUNT, clock, stop, TICK, state))
        for _ in range(1_000):
            if state.last_tick is not None and state.connected:
                break
            await asyncio.sleep(0)
        health = check(state, clock.now())
        assert health.up
        assert health.warnings == [
            "flat_ask for week 2026-10-11 sent, but its reactions cannot be counted"
        ]
        stop.set()
        await bot

    asyncio.run(scenario())
    assert not state.connected  # the event stream ended with the bot


def test_serve_records_why_it_waits(store: Store) -> None:
    env = load_env({k: v for k, v in ENV.items() if not k.endswith("_GROUP_ID")})
    state = HealthState()
    stop = asyncio.Event()

    async def scenario() -> None:
        task = asyncio.create_task(
            serve(CONFIG, store, FakeSignalClient(), env, FixedClock(T0), stop, health=state)
        )
        for _ in range(1_000):
            if state.waiting != STARTING:
                break
            await asyncio.sleep(0)
        stop.set()
        await task

    asyncio.run(scenario())
    health = check(state, T0)
    assert health.reasons == ["not ready: no flat and no dinner group chosen"]
    assert health.setup_pending


def test_serve_records_an_unreachable_api(store: Store) -> None:
    admin = FakeSignalAdmin(number=ACCOUNT.number)
    admin.script("list_accounts", ConnectionError("starting"))
    state = HealthState()
    stop = asyncio.Event()

    async def scenario() -> None:
        task = asyncio.create_task(
            serve(
                CONFIG, store, admin, load_env(ENV), FixedClock(T0), stop, admin=admin, health=state
            )
        )
        for _ in range(1_000):
            if state.waiting != STARTING:
                break
            await asyncio.sleep(0)
        stop.set()
        await task

    asyncio.run(scenario())
    assert not check(state, T0).setup_pending


def test_serve_starts_no_server_without_a_port(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def start_server(*_: object) -> None:
        raise AssertionError("no server without a port")

    monkeypatch.setattr("odin.app.start_server", start_server)
    stop = asyncio.Event()
    stop.set()
    asyncio.run(serve(CONFIG, store, FakeSignalClient(), load_env(ENV), FixedClock(T0), stop))


def test_serve_starts_and_closes_the_server_on_its_port(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []

    class Server:
        def close(self) -> None:
            calls.append("close")

        async def wait_closed(self) -> None:
            calls.append("closed")

    async def start_server(state: HealthState, clock: object, port: int) -> Server:
        calls.append(port)
        return Server()

    monkeypatch.setattr("odin.app.start_server", start_server)
    stop = asyncio.Event()
    stop.set()
    clock = FixedClock(T0)
    asyncio.run(
        serve(CONFIG, store, FakeSignalClient(), load_env(ENV), clock, stop, health_port=8081)
    )
    assert calls == [8081, "close", "closed"]


# --- ODIN_HEALTH_PORT ---------------------------------------------------------------------------


def test_health_port_default_and_off() -> None:
    assert load_env(ENV).health_port == 8081
    assert load_env({**ENV, "ODIN_HEALTH_PORT": "0"}).health_port == 0
    assert load_env({**ENV, "ODIN_HEALTH_PORT": " 9000 "}).health_port == 9000


@pytest.mark.parametrize("value", ["-1", "http", "65536", "80.5"])
def test_health_port_must_be_a_port(value: str) -> None:
    with pytest.raises(ConfigError, match="ODIN_HEALTH_PORT"):
        load_env({**ENV, "ODIN_HEALTH_PORT": value})


def test_a_busy_health_port_does_not_stop_the_bot(
    store: Store, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def start_server(*_: object) -> None:
        raise OSError(98, "Address already in use")

    monkeypatch.setattr("odin.app.start_server", start_server)
    stop = asyncio.Event()
    stop.set()
    env = load_env(ENV)
    asyncio.run(serve(CONFIG, store, FakeSignalClient(), env, FixedClock(T0), stop, health_port=1))
    assert "cannot serve the health endpoint on port 1" in caplog.text
