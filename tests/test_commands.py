import re
from collections.abc import Iterator
from datetime import UTC, datetime, time

import pytest

import odin.commands
from odin.commands import COMMANDS, Command, CommandContext, CommandError, handle, ui
from odin.commands.core import parse
from odin.commands.help import HELP
from odin.config import WeeklyTime, parse_config
from odin.store import Store

TEMPLATES = {
    "flat_ask": "Abendessen? {emoji} bis {deadline}",
    "nudge": "Noch kein {emoji}",
    "cancellation": "Abgesagt.\n\nCancelled.",
    "announcement": "Kochen {cook_time}, Essen {dinner_time}, {emoji} bis {rsvp_by}",
    "tally": "{count} mal {emoji}",
    "hello": "Hallo",
    "flat_test": "Test",
}
CONFIG = parse_config({"templates": TEMPLATES})
NOW = datetime(2026, 10, 6, 19, 0, tzinfo=CONFIG.timezone)


@pytest.fixture
def ctx() -> Iterator[CommandContext]:
    with Store(":memory:") as store:
        yield CommandContext(
            base=CONFIG,
            config=CONFIG,
            store=store,
            now=NOW,
            sender="+4915100000001",
            sender_name="Anna",
        )


def echo(ctx: CommandContext, args: str) -> list[str]:
    return [f"args={args!r}"]


def fail(ctx: CommandContext, args: str) -> list[str]:
    raise CommandError("Das geht so nicht.")


ECHO = Command(name="echo", usage="/echo <text>", summary="Wiederholt den Text.", run=echo)
FAIL = Command(name="fail", usage="/fail", summary="Schlägt fehl.", run=fail)


@pytest.fixture
def test_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(odin.commands, "COMMANDS", [*COMMANDS, ECHO, FAIL])


# --- Parsing ------------------------------------------------------------------------------------


@pytest.mark.usefixtures("test_commands")
@pytest.mark.parametrize("text", ["/echo hi", "!echo hi", "  /echo hi", "\n!echo   hi  "])
def test_both_prefixes(ctx: CommandContext, text: str) -> None:
    assert handle(text, ctx) == ["args='hi'"]


@pytest.mark.usefixtures("test_commands")
@pytest.mark.parametrize("text", ["/ECHO hi", "!Echo hi", "/eChO hi"])
def test_name_is_case_insensitive(ctx: CommandContext, text: str) -> None:
    assert handle(text, ctx) == ["args='hi'"]


@pytest.mark.usefixtures("test_commands")
def test_args_keep_newlines(ctx: CommandContext) -> None:
    text = "/echo cancellation\nAbgesagt.\n\n  Cancelled.\n"
    args = "cancellation\nAbgesagt.\n\n  Cancelled."
    assert handle(text, ctx) == [f"args={args!r}"]


@pytest.mark.usefixtures("test_commands")
def test_args_may_start_on_the_next_line(ctx: CommandContext) -> None:
    assert handle("/echo\nzweite Zeile", ctx) == ["args='zweite Zeile'"]


@pytest.mark.usefixtures("test_commands")
def test_no_args(ctx: CommandContext) -> None:
    assert handle("/echo", ctx) == ["args=''"]
    assert handle("/echo   ", ctx) == ["args=''"]


@pytest.mark.parametrize(
    "text", ["", "   ", "hello", "hallo /help", "!!!", "/", "/ ", "! help", "!1", "/1help", "/ä"]
)
def test_non_commands_get_no_reply(ctx: CommandContext, text: str) -> None:
    assert parse(text) is None
    assert handle(text, ctx) == []


def test_parse() -> None:
    invocation = parse(" !Settext tally\n{count}× {emoji}")
    assert invocation is not None
    assert (invocation.word, invocation.name, invocation.args) == (
        "!Settext",
        "settext",
        "tally\n{count}× {emoji}",
    )


# --- Dispatch -----------------------------------------------------------------------------------


def test_unknown_command(ctx: CommandContext) -> None:
    assert handle("/foo bar", ctx) == ["Unbekannter Befehl /foo – /help zeigt alle Befehle."]


@pytest.mark.parametrize("text", ["/help2", "!help-me", "/help:"])
def test_command_word_with_non_letters_is_unknown(ctx: CommandContext, text: str) -> None:
    assert handle(text, ctx) == [ui.UNKNOWN_COMMAND.format(command=text)]


@pytest.mark.usefixtures("test_commands")
def test_command_error_becomes_the_reply(ctx: CommandContext) -> None:
    assert handle("/fail", ctx) == ["Das geht so nicht."]


def test_other_exceptions_propagate(ctx: CommandContext, monkeypatch: pytest.MonkeyPatch) -> None:
    def crash(ctx: CommandContext, args: str) -> list[str]:
        raise RuntimeError("boom")

    crashing = Command(name="crash", usage="/crash", summary="Stürzt ab.", run=crash)
    monkeypatch.setattr(odin.commands, "COMMANDS", [crashing])
    with pytest.raises(RuntimeError):
        handle("/crash", ctx)


def test_registry_names_are_unique_lowercase_letters() -> None:
    names = [command.name for command in COMMANDS]
    assert len(names) == len(set(names))
    for command in COMMANDS:
        assert re.fullmatch(r"[a-z]+", command.name)
        assert command.usage.split()[0] == f"/{command.name}"
        assert command.summary


# --- /help --------------------------------------------------------------------------------------


def test_help(ctx: CommandContext) -> None:
    [reply] = handle("/help", ctx)
    assert "/help – Zeigt alle Befehle." in reply.splitlines()


def test_help_lists_every_registered_command_in_order(
    ctx: CommandContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A fixed registry, so the test does not change with every command added.
    monkeypatch.setattr(odin.commands, "COMMANDS", [HELP, ECHO, FAIL])
    [reply] = handle("!HELP", ctx)
    lines = reply.splitlines()
    listed = [line for line in lines if line.startswith("/")]
    assert listed == [
        "/help – Zeigt alle Befehle.",
        "/echo <text> – Wiederholt den Text.",
        "/fail – Schlägt fehl.",
    ]


# --- Shared UI strings --------------------------------------------------------------------------


def test_weekly_time() -> None:
    assert ui.weekly_time(WeeklyTime(1, time(18, 0))) == "Di 18:00"
    assert ui.weekly_time(WeeklyTime(6, time(9, 5))) == "So 09:05"


def test_override_marker_uses_the_local_date() -> None:
    # 22:30 UTC on 11 Oct is already 12 Oct in Berlin.
    changed_at = datetime(2026, 10, 11, 22, 30, tzinfo=UTC)
    assert ui.override_marker("Tim", changed_at, CONFIG.timezone) == "✏️ 12.10. von Tim"
