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

    def connect(url: str, number: str) -> ClosableFakeAdmin:
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

    async def serve(config, store, client, env_, clock, stop, admin) -> None:
        served.append((store, client, admin, clock, env_.signal_number))
        os.kill(os.getpid(), signal.SIGTERM)  # handled by the bot: sets stop
        await stop.wait()

    monkeypatch.setattr("odin.cli.serve", serve)
    assert main(["run"], env, CLOCK) == 0
    [(store, client, admin_, clock, number)] = served
    assert isinstance(store, Store)
    assert (client, admin_, clock, number) == (admin, admin, CLOCK, NUMBER)
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
