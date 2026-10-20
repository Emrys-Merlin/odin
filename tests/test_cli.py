"""The `odin` command's wiring: each subcommand with a fake Signal API instead of the real one."""

import logging
import os
import signal
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from odin.app import DINNER_GROUP_KEY, FLAT_GROUP_KEY
from odin.cli import main
from odin.clock import FixedClock
from odin.setup import SetupOptions
from odin.signal import FakeSignalAdmin, Group
from odin.store import Store
from odin.terminal import ScriptedTerminal

EXAMPLE = Path(__file__).parent.parent / "config.example.toml"
NUMBER = "+491701234567"
CLOCK = FixedClock(datetime.fromisoformat("2026-10-06T18:05:00+02:00"))
FLAT = Group(id="group.ZmxhdA==", internal_id="flat", name="WG")
DINNER = Group(id="group.ZGlubmVy", internal_id="dinner", name="Sonntagsessen")


class ClosableFakeAdmin(FakeSignalAdmin):
    """The fake, closable like the RestSignalClient it stands in for."""

    closed = False

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    return {
        "SIGNAL_NUMBER": NUMBER,
        "SIGNAL_API_URL": "http://signal:8080",
        "ODIN_CONFIG": str(EXAMPLE),
        "ODIN_DB": str(tmp_path / "odin.db"),
    }


@pytest.fixture
def admin(monkeypatch: pytest.MonkeyPatch) -> Iterator[ClosableFakeAdmin]:
    fake = ClosableFakeAdmin(number=NUMBER, groups=[FLAT, DINNER])
    urls: list[str] = []

    def connect(url: str, number: str, **_: object) -> ClosableFakeAdmin:
        urls.append(url)
        assert number == NUMBER
        return fake

    monkeypatch.setattr("odin.cli.RestSignalClient", connect)
    yield fake
    assert urls in ([], ["http://signal:8080"])


def test_run_serves_until_sigterm_and_closes_the_client(
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    admin: ClosableFakeAdmin,
    capsys: pytest.CaptureFixture[str],
) -> None:
    served = []

    async def serve(config, store, client, env_, clock, stop, admin, health, health_port) -> None:
        served.append((store, client, admin, clock, env_.signal_number, health_port))
        os.kill(os.getpid(), signal.SIGTERM)  # handled by the bot: sets stop
        await stop.wait()

    monkeypatch.setattr("odin.cli.serve", serve)
    assert main(["run"], env, CLOCK) == 0
    [(store, client, admin_, clock, number, health_port)] = served
    assert isinstance(store, Store)
    assert (client, admin_, clock, number, health_port) == (admin, admin, CLOCK, NUMBER, 8081)
    assert Path(env["ODIN_DB"]).exists()
    assert admin.closed
    # main() logs to stdout.
    assert "INFO odin: Odin 🍽️ starting (Signal API http://signal:8080)" in capsys.readouterr().out


def test_setup_runs_the_wizard_on_the_database(
    env: dict[str, str], admin: ClosableFakeAdmin
) -> None:
    terminal = ScriptedTerminal()  # no answers: stops at the first question
    assert main(["setup"], env, CLOCK, terminal) == 1
    assert "Captcha" in terminal.text
    assert Path(env["ODIN_DB"]).exists()
    assert admin.closed
    assert logging.getLogger("httpx").level == logging.WARNING


def test_setup_passes_its_options(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], admin: ClosableFakeAdmin
) -> None:
    options: list[SetupOptions] = []

    async def run_setup(client, store, config, env_, terminal, clock, opts) -> int:
        options.append(opts)
        return 0

    monkeypatch.setattr("odin.cli.run_setup", run_setup)
    argv = ["setup", "--pin", "--redo", "hello", "--redo", "groups"]
    assert main(argv, env, CLOCK, ScriptedTerminal()) == 0
    assert options == [SetupOptions(own_pin=True, redo=frozenset({"hello", "groups"}))]


def test_setup_stopped_with_ctrl_c(
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    admin: ClosableFakeAdmin,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def run_setup(*args: object) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr("odin.cli.run_setup", run_setup)
    assert main(["setup"], env, CLOCK, ScriptedTerminal()) == 130
    assert "Stopped. Run `odin setup` again to continue." in capsys.readouterr().err
    assert admin.closed


def test_setup_status_without_a_database_creates_none(
    env: dict[str, str], admin: ClosableFakeAdmin
) -> None:
    terminal = ScriptedTerminal()
    assert main(["setup", "--status"], env, CLOCK, terminal) == 1
    assert f"✗ Registered: {NUMBER} not registered" in terminal.text
    assert not Path(env["ODIN_DB"]).exists()
    assert admin.closed


def test_setup_status_reads_the_database(env: dict[str, str], admin: ClosableFakeAdmin) -> None:
    admin.accounts.append(NUMBER)
    with Store(Path(env["ODIN_DB"])) as store:
        store.set_setting(FLAT_GROUP_KEY, FLAT.id)
        store.set_setting(DINNER_GROUP_KEY, DINNER.id)
    terminal = ScriptedTerminal()
    assert main(["setup", "--status"], env, CLOCK, terminal) == 1  # PIN, profile, … not done
    assert f"✓ Flat group: {FLAT.id} (from database) — WG" in terminal.text


def test_list_groups(
    env: dict[str, str], admin: ClosableFakeAdmin, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["list-groups"], env) == 0
    assert capsys.readouterr().out == f"Sonntagsessen\t{DINNER.id}\nWG\t{FLAT.id}\n"
    assert admin.closed


def test_list_groups_when_in_none(
    env: dict[str, str], admin: ClosableFakeAdmin, capsys: pytest.CaptureFixture[str]
) -> None:
    admin.groups.clear()
    assert main(["list-groups"], env) == 0
    assert capsys.readouterr().out == "The bot is not a member of any group.\n"


def test_an_unreachable_signal_api_exits_with_1(
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    admin: ClosableFakeAdmin,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def list_groups() -> list[Group]:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(admin, "list_groups", list_groups)
    assert main(["list-groups"], env) == 1
    assert capsys.readouterr().err == "odin: ConnectError: connection refused\n"
    assert admin.closed


# --- odin health --------------------------------------------------------------------------------


def _health_answer(
    monkeypatch: pytest.MonkeyPatch, status: int, body: object, urls: list[str] | None = None
) -> None:
    def get(url: str, **_: object) -> httpx.Response:
        if urls is not None:
            urls.append(url)
        return httpx.Response(status, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr("odin.cli.httpx.get", get)


UP = {"status": "up", "reasons": [], "warnings": [], "setup_pending": False, "version": "1.2.3"}
DOWN = {**UP, "status": "down", "reasons": ["Signal event connection not up yet"]}
NOT_SET_UP = {**DOWN, "reasons": ["not ready: no flat group chosen"], "setup_pending": True}


def test_health_up(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    urls: list[str] = []
    warned = {**UP, "warnings": ["announcement for week 2026-10-11 sent, but …"]}
    _health_answer(monkeypatch, 200, warned, urls)
    assert main(["health"], {}) == 0  # needs no other env var
    assert urls == ["http://localhost:8081/health"]
    out = capsys.readouterr().out
    assert "up (HTTP 200, version 1.2.3)" in out
    assert "warning: announcement for week 2026-10-11 sent, but …" in out


def test_health_down(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    urls: list[str] = []
    _health_answer(monkeypatch, 503, DOWN, urls)
    assert main(["health"], {"ODIN_HEALTH_PORT": "9000"}) == 1
    assert urls == ["http://localhost:9000/health"]
    assert "down: Signal event connection not up yet" in capsys.readouterr().out


def test_health_setup_ok_passes_only_while_waiting_for_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _health_answer(monkeypatch, 503, NOT_SET_UP)
    assert main(["health"], {}) == 1
    assert main(["health", "--setup-ok"], {}) == 0
    _health_answer(monkeypatch, 503, DOWN)
    assert main(["health", "--setup-ok"], {}) == 1


def test_health_unreachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def get(url: str, **_: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("odin.cli.httpx.get", get)
    assert main(["health", "--setup-ok"], {}) == 1
    assert "no answer from http://localhost:8081/health: ConnectError" in capsys.readouterr().err


def test_health_unexpected_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    _health_answer(monkeypatch, 200, ["up"])
    assert main(["health"], {}) == 1


def test_health_off(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _health_answer(monkeypatch, 200, UP)
    assert main(["health"], {"ODIN_HEALTH_PORT": "0"}) == 1
    assert "the health endpoint is off" in capsys.readouterr().err
    assert main(["health"], {"ODIN_HEALTH_PORT": "x"}) == 2
