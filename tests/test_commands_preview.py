from collections.abc import Iterator
from datetime import date, datetime

import pytest

from odin.commands.preview import render_preview
from odin.config import parse_config
from odin.store import MessageKind, Store

TEMPLATES = {
    "flat_ask": "Essen am {dinner_day_de}? {emoji} bis {deadline}",
    "nudge": "Noch kein {emoji}",
    "cancellation": "Abgesagt.\n\nCancelled.",
    "announcement": "Kochen {cook_time}, Essen {dinner_time}",
    "tally": "{count} mal {emoji}",
    "hello": "Hallo",
    "flat_test": "Test",
}
CONFIG = parse_config({"templates": TEMPLATES})
WEEK = date(2026, 10, 11)
NOW = datetime(2026, 10, 9, 10, 0, tzinfo=CONFIG.timezone)  # Friday before WEEK's dinner


@pytest.fixture
def store() -> Iterator[Store]:
    with Store(":memory:") as store:
        yield store


def announce(store: Store, week: date, reactions: dict[str, str]) -> None:
    message = store.track_message(week, MessageKind.DINNER_ANNOUNCEMENT, "group.d=", "+49", 1)
    for reactor, emoji in reactions.items():
        store.set_reaction(message, reactor, emoji, NOW)


def test_renders_with_the_current_values(store: Store) -> None:
    assert render_preview(CONFIG, store, "flat_ask", NOW) == (
        "Essen am Sonntag? 👍 bis 18:00",
        False,
    )
    assert render_preview(CONFIG, store, "cancellation", NOW) == (
        "Abgesagt.\n\nCancelled.",
        False,
    )


def test_tally_without_announcement_uses_a_sample_count(store: Store) -> None:
    assert render_preview(CONFIG, store, "tally", NOW) == ("3 mal 👍", True)


def test_tally_counts_the_confirmations_on_this_weeks_announcement(store: Store) -> None:
    announce(store, WEEK, {"+491": "👍", "+492": "👍🏽", "+493": "❤️"})
    assert render_preview(CONFIG, store, "tally", NOW) == ("2 mal 👍", False)


def test_tally_with_no_confirmations_is_not_a_sample(store: Store) -> None:
    announce(store, WEEK, {})
    assert render_preview(CONFIG, store, "tally", NOW) == ("0 mal 👍", False)


def test_tally_ignores_the_announcement_of_another_week(store: Store) -> None:
    announce(store, date(2026, 10, 4), {"+491": "👍"})
    assert render_preview(CONFIG, store, "tally", NOW) == ("3 mal 👍", True)
