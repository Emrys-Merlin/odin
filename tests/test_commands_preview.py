from collections.abc import Iterator
from datetime import date, datetime

import pytest

from odin.commands.preview import render_preview
from odin.config import parse_config
from odin.overrides import EDITABLE_TEMPLATES
from odin.store import MessageKind, Store

TEMPLATES = {
    "flat_ask": "Essen am {dinner_day_de}? {emoji} bis {deadline_day_de} {deadline}",
    "nudge": "Noch kein {emoji}",
    "cancellation": "Abgesagt.\n\nCancelled.",
    "announcement": "Kochen {cook_time}, Essen {dinner_time}, {emoji} bis {rsvp_by}",
    "tally": "{count} mal {emoji}",
    "hello": "Hallo",
    "flat_test": "Test",
}
CONFIG = parse_config({"templates": TEMPLATES})
NOW = datetime(2026, 10, 8, 10, 0, tzinfo=CONFIG.timezone)  # Thu; dinner week of Sun 11 Oct
WEEK = date(2026, 10, 11)
GROUP = "group.dinner"
BOT = "+4915100000001"


@pytest.fixture
def store() -> Iterator[Store]:
    with Store(":memory:") as store:
        yield store


def announce(store: Store, week: date, reactions: dict[str, str]) -> None:
    message = store.track_message(week, MessageKind.DINNER_ANNOUNCEMENT, GROUP, BOT, 1000)
    for reactor, emoji in reactions.items():
        store.set_reaction(message, reactor, emoji, NOW)


def test_renders_with_placeholder_values(store: Store) -> None:
    assert render_preview(CONFIG, store, "flat_ask", NOW) == (
        "Essen am Sonntag? 👍 bis Mittwoch 18:00",
        False,
    )
    assert render_preview(CONFIG, store, "announcement", NOW) == (
        "Kochen 17:00, Essen 18:00, 👍 bis 14:00",
        False,
    )


@pytest.mark.parametrize("name", EDITABLE_TEMPLATES)
def test_every_editable_template_renders(store: Store, name: str) -> None:
    text, _ = render_preview(CONFIG, store, name, NOW)
    assert "{" not in text


def test_tally_without_announcement_uses_sample_count(store: Store) -> None:
    assert render_preview(CONFIG, store, "tally", NOW) == ("3 mal 👍", True)


def test_tally_counts_confirmations_on_this_weeks_announcement(store: Store) -> None:
    announce(store, WEEK, {"+491": "👍", "+492": "👍🏽", "+493": "❤️"})
    assert render_preview(CONFIG, store, "tally", NOW) == ("2 mal 👍", False)


def test_tally_with_announcement_but_no_reactions_is_zero(store: Store) -> None:
    announce(store, WEEK, {})
    assert render_preview(CONFIG, store, "tally", NOW) == ("0 mal 👍", False)


def test_tally_ignores_last_weeks_announcement(store: Store) -> None:
    announce(store, date(2026, 10, 4), {"+491": "👍"})
    assert render_preview(CONFIG, store, "tally", NOW) == ("3 mal 👍", True)
