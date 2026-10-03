import asyncio
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from odib.app import (
    DINNER_GROUP_KEY,
    FLAT_GROUP_KEY,
    GroupSetting,
    Source,
    readiness,
    resolve_account,
    run_bot,
    serve,
    upcoming_actions,
)
from odib.cli import main
from odib.clock import FixedClock
from odib.config import load_config, load_env
from odib.engine import Account
from odib.signal import FakeSignalClient, ReactionEvent
from odib.store import Action, MessageKind, Store

EXAMPLE = Path(__file__).parent.parent / "config.example.toml"
CONFIG = load_config(EXAMPLE)
BERLIN = CONFIG.timezone

ENV = {
    "SIGNAL_NUMBER": "+491701234567",
    "FLAT_GROUP_ID": "group.ZmxhdA==",
    "DINNER_GROUP_ID": "group.ZGlubmVy",
    "SIGNAL_API_URL": "http://signal:8080",
    "ODIB_CONFIG": str(EXAMPLE),
    "ODIB_DB": "/data/odib.db",
}
NO_GROUPS = {k: v for k, v in ENV.items() if not k.endswith("_GROUP_ID")}
_account = resolve_account(load_env(ENV), None).account
assert _account is not None
ACCOUNT = _account
ANNA = "+4915100000001"

# Dinner on Sunday 2026-10-11; flat ask on Tuesday 2026-10-06 18:00.
WEEK = date(2026, 10, 11)


def local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=BERLIN)


async def until(condition: Callable[[], bool]) -> None:
    """Let other tasks run until `condition` holds; no real time passes."""
    for _ in range(1_000):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition never became true")


@pytest.fixture
def store() -> Iterator[Store]:
    with Store(":memory:") as s:
        yield s


# --- group IDs: env, then database, then not set up ----------------------------------------------


def test_resolve_account_from_env() -> None:
    assert (
        Account(
            number="+491701234567", flat_group_id="group.ZmxhdA==", dinner_group_id="group.ZGlubmVy"
        )
        == ACCOUNT
    )


def test_resolve_account_from_the_database(store: Store) -> None:
    env = load_env(NO_GROUPS)
    store.set_setting(FLAT_GROUP_KEY, "group.db-flat=")
    store.set_setting(DINNER_GROUP_KEY, "group.db-dinner=")
    resolution = resolve_account(env, store)
    assert resolution.flat == GroupSetting("group.db-flat=", Source.DB)
    assert resolution.dinner == GroupSetting("group.db-dinner=", Source.DB)
    assert resolution.account == Account(ACCOUNT.number, "group.db-flat=", "group.db-dinner=")


def test_env_overrides_the_database_per_group(store: Store) -> None:
    env = load_env({**NO_GROUPS, "DINNER_GROUP_ID": "group.env-dinner="})
    store.set_setting(FLAT_GROUP_KEY, "group.db-flat=")
    store.set_setting(DINNER_GROUP_KEY, "group.db-dinner=")
    resolution = resolve_account(env, store)
    assert resolution.flat == GroupSetting("group.db-flat=", Source.DB)
    assert resolution.dinner == GroupSetting("group.env-dinner=", Source.ENV)


def test_not_set_up(store: Store) -> None:
    env = load_env(NO_GROUPS)
    resolution = resolve_account(env, store)
    assert resolution.account is None
    assert resolution.flat == GroupSetting(None, Source.UNSET)
    assert resolution.missing == "no flat and no dinner group chosen"

    store.set_setting(FLAT_GROUP_KEY, "group.db-flat=")
    resolution = resolve_account(env, store)
    assert resolution.account is None
    assert resolution.missing == "no dinner group chosen"


def test_readiness_waits_for_the_setup_lock(store: Store) -> None:
    env = load_env(ENV)
    now = local(6, 12)
    assert readiness(env, store, now) == (ACCOUNT, "")
    token = store.acquire_setup_lock(now)
    assert token is not None
    assert readiness(env, store, now) == (None, "odib setup is running")
    store.release_setup_lock(token)
    assert readiness(env, store, now) == (ACCOUNT, "")


# --- run_bot ------------------------------------------------------------------------------------


def test_one_tick_sends_the_flat_ask_and_shuts_down(store: Store) -> None:
    client = FakeSignalClient(number=ACCOUNT.number)
    clock = FixedClock(local(6, 18, 5))

    async def scenario() -> None:
        stop = asyncio.Event()
        bot = asyncio.create_task(run_bot(CONFIG, store, client, ACCOUNT, clock, stop))
        await until(lambda: len(client.sent) == 1)
        stop.set()
        await bot

    asyncio.run(scenario())

    [sent] = client.sent
    assert sent.group_id == ACCOUNT.flat_group_id
    assert sent.text.startswith("Findet am Sonntag das offene Abendessen statt?")
    assert "Mittwoch 18:00 mit 👍" in sent.text
    assert store.has_action(WEEK, Action.FLAT_ASK)


def test_reactions_are_consumed_while_ticking(store: Store) -> None:
    client = FakeSignalClient(number=ACCOUNT.number)
    clock = FixedClock(local(6, 18, 5))

    async def scenario() -> None:
        stop = asyncio.Event()
        bot = asyncio.create_task(
            run_bot(CONFIG, store, client, ACCOUNT, clock, stop, tick_interval=timedelta(0))
        )
        await until(lambda: len(client.sent) == 1)
        poll = store.tracked_message(WEEK, MessageKind.FLAT_POLL)
        assert poll is not None
        client.inject(
            ReactionEvent(
                emoji="👍",
                reactor=ANNA,
                target_author=poll.author,
                target_timestamp=poll.timestamp,
                group_id=poll.group_id,
                is_remove=False,
                timestamp=int(local(6, 20).timestamp() * 1000),
            )
        )
        await until(lambda: len(store.reactions_for(poll)) == 1)

        clock.set(local(7, 18))
        await until(lambda: len(client.sent) == 2)
        stop.set()
        await bot

    asyncio.run(scenario())

    announcement = client.sent[1]
    assert announcement.group_id == ACCOUNT.dinner_group_id
    assert announcement.text.startswith("Diesen Sonntag gibt es offenes Abendessen!")
    assert store.has_action(WEEK, Action.ANNOUNCEMENT)


def test_a_failing_tick_does_not_stop_the_bot(store: Store) -> None:
    class FailOnce(FakeSignalClient):
        failed = False

        async def send_group_message(self, group_id: str, text: str) -> int:
            if not self.failed:
                self.failed = True
                raise ConnectionError("signal-cli-rest-api unreachable")
            return await super().send_group_message(group_id, text)

    client = FailOnce(number=ACCOUNT.number)
    clock = FixedClock(local(6, 18, 5))

    async def scenario() -> None:
        stop = asyncio.Event()
        bot = asyncio.create_task(
            run_bot(CONFIG, store, client, ACCOUNT, clock, stop, tick_interval=timedelta(0))
        )
        await until(lambda: len(client.sent) == 1)
        stop.set()
        await bot

    asyncio.run(scenario())
    assert client.failed


def test_the_bot_fails_when_the_event_stream_ends(store: Store) -> None:
    client = FakeSignalClient(number=ACCOUNT.number)
    clock = FixedClock(local(6, 12))  # nothing due
    client.close()

    with pytest.raises(RuntimeError, match="event stream ended"):
        asyncio.run(run_bot(CONFIG, store, client, ACCOUNT, clock, asyncio.Event()))


# --- serve: run only while set up -----------------------------------------------------------------

FAST = {"check_interval": timedelta(0), "tick_interval": timedelta(0)}


def test_serve_waits_until_set_up_and_then_starts_without_restart(
    store: Store, caplog: pytest.LogCaptureFixture
) -> None:
    env = load_env(NO_GROUPS)
    client = FakeSignalClient(number=ACCOUNT.number)
    clock = FixedClock(local(6, 18, 5))  # the flat ask is due

    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(serve(CONFIG, store, client, env, clock, stop, **FAST))
        await until(lambda: "not set up yet" in caplog.text)
        for _ in range(20):
            await asyncio.sleep(0)
        assert client.sent == []

        store.set_setting(FLAT_GROUP_KEY, "group.flat=")  # what odib setup will do
        store.set_setting(DINNER_GROUP_KEY, "group.dinner=")
        await until(lambda: len(client.sent) == 1)
        stop.set()
        await task

    with caplog.at_level("INFO", logger="odib"):
        asyncio.run(scenario())

    assert client.sent[0].group_id == "group.flat="
    waiting = [r.getMessage() for r in caplog.records if "not set up yet" in r.getMessage()]
    assert waiting == [
        "ODIN is not set up yet (no flat and no dinner group chosen)"
        " — run: podman exec -it odib odib setup"
    ]  # logged once, not on every check
    assert "flat group group.flat= (from database)" in caplog.text


def test_serve_pauses_while_setup_runs(store: Store, caplog: pytest.LogCaptureFixture) -> None:
    env = load_env(ENV)
    client = FakeSignalClient(number=ACCOUNT.number)
    clock = FixedClock(local(6, 12))  # nothing due yet

    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(serve(CONFIG, store, client, env, clock, stop, **FAST))
        await until(lambda: "flat group" in caplog.text)  # the bot is running
        token = store.acquire_setup_lock(clock.now())
        assert token is not None
        await until(lambda: "odib setup is running" in caplog.text)

        clock.set(local(6, 18, 5))  # the flat ask becomes due while setup runs
        store.refresh_setup_lock(token, clock.now())
        for _ in range(50):
            await asyncio.sleep(0)
        assert client.sent == []

        store.release_setup_lock(token)
        await until(lambda: len(client.sent) == 1)
        stop.set()
        await task

    with caplog.at_level("INFO", logger="odib"):
        asyncio.run(scenario())
    assert client.sent[0].group_id == ACCOUNT.flat_group_id


def test_serve_picks_up_a_new_group_choice(store: Store) -> None:
    env = load_env(NO_GROUPS)
    store.set_setting(FLAT_GROUP_KEY, "group.old-flat=")
    store.set_setting(DINNER_GROUP_KEY, "group.dinner=")
    client = FakeSignalClient(number=ACCOUNT.number)
    clock = FixedClock(local(6, 12))

    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(serve(CONFIG, store, client, env, clock, stop, **FAST))
        for _ in range(20):
            await asyncio.sleep(0)
        store.set_setting(FLAT_GROUP_KEY, "group.new-flat=")
        for _ in range(20):
            await asyncio.sleep(0)
        clock.set(local(6, 18, 5))
        await until(lambda: len(client.sent) == 1)
        stop.set()
        await task

    asyncio.run(scenario())
    assert client.sent[0].group_id == "group.new-flat="


def test_serve_stops_while_waiting(store: Store) -> None:
    env = load_env(NO_GROUPS)
    stop = asyncio.Event()
    stop.set()
    client = FakeSignalClient(number=ACCOUNT.number)
    asyncio.run(serve(CONFIG, store, client, env, FixedClock(local(6, 12)), stop))
    assert client.sent == []


def test_serve_fails_when_the_event_stream_ends(store: Store) -> None:
    client = FakeSignalClient(number=ACCOUNT.number)
    client.close()
    env = load_env(ENV)
    with pytest.raises(RuntimeError, match="event stream ended"):
        asyncio.run(
            serve(CONFIG, store, client, env, FixedClock(local(6, 12)), asyncio.Event(), **FAST)
        )


# --- upcoming_actions ---------------------------------------------------------------------------


def test_upcoming_actions_mid_week() -> None:
    upcoming = upcoming_actions(CONFIG, local(7, 13))  # Wednesday, after the nudge
    assert [(u.name, u.at) for u in upcoming] == [
        ("announcement / cancellation", local(7, 18)),
        ("tally", local(9, 14)),
        ("flat ask", local(13, 18)),
        ("nudge", local(14, 12)),
    ]


def test_upcoming_actions_include_one_due_right_now() -> None:
    assert upcoming_actions(CONFIG, local(6, 18))[0].name == "flat ask"


# --- CLI ----------------------------------------------------------------------------------------


def test_check_config_with_the_example_config(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["check-config"], ENV, FixedClock(local(3, 12)))
    out = capsys.readouterr().out
    assert code == 0
    assert f"Config OK: {EXAMPLE}" in out
    assert "Flat group:   group.ZmxhdA== (from env var)" in out
    assert "Dinner group: group.ZGlubmVy (from env var)" in out
    lines = out.split("Next scheduled actions:\n")[1].splitlines()
    assert lines == [
        "  Tue 2026-10-06 18:00  flat ask (flat group)",
        "  Wed 2026-10-07 12:00  nudge (flat group, only if nobody confirmed)",
        "  Wed 2026-10-07 18:00  announcement / cancellation (dinner group)",
        "  Fri 2026-10-09 14:00  tally (flat group, only if dinner is on)",
    ]


def test_check_config_shows_where_group_ids_come_from(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "odib.db"
    with Store(db) as store:
        store.set_setting(FLAT_GROUP_KEY, "group.db-flat=")
        store.set_setting(DINNER_GROUP_KEY, "group.db-dinner=")
    env = {**NO_GROUPS, "ODIB_DB": str(db), "DINNER_GROUP_ID": "group.env-dinner="}
    assert main(["check-config"], env, FixedClock(local(3, 12))) == 0
    out = capsys.readouterr().out
    assert "Flat group:   group.db-flat= (from database)" in out
    assert "Dinner group: group.env-dinner= (from env var)" in out
    assert "Not set up" not in out


def test_check_config_reports_not_set_up(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "odib.db"
    env = {**NO_GROUPS, "ODIB_DB": str(db)}
    assert main(["check-config"], env, FixedClock(local(3, 12))) == 0
    out = capsys.readouterr().out
    assert "Flat group:   -" in out
    assert (
        "Not set up yet (no flat and no dinner group chosen) — run: podman exec -it odib odib setup"
    ) in out
    assert "Next scheduled actions:" in out
    assert not db.exists()  # check-config never creates the database


def test_check_config_reports_a_missing_env_var(capsys: pytest.CaptureFixture[str]) -> None:
    env = {k: v for k, v in ENV.items() if k != "ODIB_DB"}
    assert main(["check-config"], env) == 2
    assert "ODIB_DB" in capsys.readouterr().err


def test_check_config_reports_a_bad_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "config.toml"
    path.write_text('emoji = ""\n')
    assert main(["check-config"], {**ENV, "ODIB_CONFIG": str(path)}) == 2
    assert "emoji" in capsys.readouterr().err


def test_invalid_log_level(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check-config"], {**ENV, "ODIB_LOG_LEVEL": "chatty"}) == 2
    assert "ODIB_LOG_LEVEL" in capsys.readouterr().err


def test_list_groups_needs_only_the_signal_env(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list-groups"], {}) == 2
    assert "SIGNAL_NUMBER" in capsys.readouterr().err


def test_a_command_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit:
        main([], ENV)
    assert exit.value.code == 2
