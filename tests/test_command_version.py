from collections.abc import Iterator
from datetime import datetime

import pytest

import odin
from odin.commands import CommandContext, handle
from odin.config import parse_config
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


@pytest.mark.parametrize("text", ["/version", "!version", "/VERSION", "/version egal"])
def test_version_replies_with_the_running_version(
    ctx: CommandContext, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    monkeypatch.setattr(odin, "__version__", "1.2.3")
    assert handle(text, ctx) == ["Odin 🍽️ läuft in Version 1.2.3."]


def test_version_is_the_package_version(ctx: CommandContext) -> None:
    [reply] = handle("/version", ctx)
    assert odin.__version__ in reply


def test_help_lists_version(ctx: CommandContext) -> None:
    [reply] = handle("/help", ctx)
    assert "/version – Zeigt, welche Version von Odin läuft." in reply.splitlines()
