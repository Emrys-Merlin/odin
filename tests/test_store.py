import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from odib.store import (
    SCHEMA_VERSION,
    SETUP_LOCK_TTL,
    Action,
    MessageKind,
    Outcome,
    Reaction,
    Store,
)

BERLIN = timezone(timedelta(hours=2))
UTC_MINUS_5 = timezone(timedelta(hours=-5))
WEEK = date(2026, 10, 11)
TUE = datetime(2026, 10, 6, 18, 0, tzinfo=BERLIN)
BOT = "+4915100000000"


@pytest.fixture
def store():
    with Store(":memory:") as s:
        yield s


def test_record_action_is_idempotent(store: Store) -> None:
    assert not store.has_action(WEEK, Action.FLAT_ASK)
    assert store.action_time(WEEK, Action.FLAT_ASK) is None

    assert store.record_action(WEEK, Action.FLAT_ASK, TUE)
    assert not store.record_action(WEEK, Action.FLAT_ASK, TUE + timedelta(hours=1))

    assert store.has_action(WEEK, Action.FLAT_ASK)
    assert store.action_time(WEEK, Action.FLAT_ASK) == TUE


def test_actions_are_per_week_and_kind(store: Store) -> None:
    store.record_action(WEEK, Action.FLAT_ASK, TUE)
    assert not store.has_action(WEEK, Action.NUDGE)
    assert not store.has_action(WEEK + timedelta(weeks=1), Action.FLAT_ASK)


def test_action_outcome(store: Store) -> None:
    assert store.action_outcome(WEEK, Action.NUDGE) is None
    store.record_action(WEEK, Action.FLAT_ASK, TUE)
    store.record_action(WEEK, Action.NUDGE, TUE, Outcome.SKIPPED)
    assert store.action_outcome(WEEK, Action.FLAT_ASK) is Outcome.SENT
    assert store.action_outcome(WEEK, Action.NUDGE) is Outcome.SKIPPED
    assert store.has_action(WEEK, Action.NUDGE)


def test_transaction_rolls_back_on_error(store: Store) -> None:
    with pytest.raises(RuntimeError), store.transaction():
        store.record_action(WEEK, Action.FLAT_ASK, TUE)
        raise RuntimeError
    assert not store.has_action(WEEK, Action.FLAT_ASK)

    with store.transaction():
        store.record_action(WEEK, Action.FLAT_ASK, TUE)
    assert store.has_action(WEEK, Action.FLAT_ASK)


def test_naive_datetimes_are_rejected(store: Store) -> None:
    with pytest.raises(ValueError, match="naive"):
        store.record_action(WEEK, Action.FLAT_ASK, datetime(2026, 10, 6, 18, 0))


def test_track_and_find_message(store: Store) -> None:
    assert store.tracked_message(WEEK, MessageKind.FLAT_POLL) is None

    msg = store.track_message(WEEK, MessageKind.FLAT_POLL, "flat-group", BOT, 1_000)

    assert store.tracked_message(WEEK, MessageKind.FLAT_POLL) == msg
    assert store.tracked_message(WEEK, MessageKind.DINNER_ANNOUNCEMENT) is None
    assert store.find_message(BOT, 1_000) == msg
    assert store.find_message(BOT, 1_001) is None


def test_one_message_per_week_and_kind(store: Store) -> None:
    store.track_message(WEEK, MessageKind.FLAT_POLL, "flat-group", BOT, 1_000)
    with pytest.raises(sqlite3.IntegrityError):
        store.track_message(WEEK, MessageKind.FLAT_POLL, "flat-group", BOT, 2_000)


def test_reaction_add_replace_remove(store: Store) -> None:
    msg = store.track_message(WEEK, MessageKind.FLAT_POLL, "flat-group", BOT, 1_000)
    assert store.reactions_for(msg) == []

    store.set_reaction(msg, "+49alice", "👍", TUE)
    store.set_reaction(msg, "+49bob", "❤️", TUE + timedelta(minutes=1))
    assert store.reactions_for(msg) == [
        Reaction("+49alice", "👍", TUE),
        Reaction("+49bob", "❤️", TUE + timedelta(minutes=1)),
    ]

    # A new emoji from the same person replaces the old one.
    store.set_reaction(msg, "+49bob", "👍", TUE + timedelta(minutes=2))
    assert store.reactions_for(msg) == [
        Reaction("+49alice", "👍", TUE),
        Reaction("+49bob", "👍", TUE + timedelta(minutes=2)),
    ]

    assert store.remove_reaction(msg, "+49alice")
    assert not store.remove_reaction(msg, "+49alice")
    assert store.reactions_for(msg) == [Reaction("+49bob", "👍", TUE + timedelta(minutes=2))]


def test_stale_removal_keeps_current_reaction(store: Store) -> None:
    msg = store.track_message(WEEK, MessageKind.FLAT_POLL, "flat-group", BOT, 1_000)
    store.set_reaction(msg, "+49bob", "👍", TUE)

    assert not store.remove_reaction(msg, "+49bob", "❤️")
    assert store.reactions_for(msg) == [Reaction("+49bob", "👍", TUE)]
    assert store.remove_reaction(msg, "+49bob", "👍")
    assert store.reactions_for(msg) == []


def test_reactions_are_per_message(store: Store) -> None:
    poll = store.track_message(WEEK, MessageKind.FLAT_POLL, "flat-group", BOT, 1_000)
    ann = store.track_message(WEEK, MessageKind.DINNER_ANNOUNCEMENT, "dinner-group", BOT, 2_000)
    store.set_reaction(poll, "+49alice", "👍", TUE)

    assert store.reactions_for(ann) == []


def test_reactions_ordered_chronologically_across_offsets(store: Store) -> None:
    msg = store.track_message(WEEK, MessageKind.FLAT_POLL, "flat-group", BOT, 1_000)
    earlier_elsewhere = (TUE + timedelta(minutes=30)).astimezone(UTC_MINUS_5)
    store.set_reaction(msg, "+49late", "👍", TUE + timedelta(hours=1))
    store.set_reaction(msg, "+49early", "👍", earlier_elsewhere)

    assert [r.reactor for r in store.reactions_for(msg)] == ["+49early", "+49late"]


def test_data_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "odib.sqlite"
    with Store(path) as store:
        store.record_action(WEEK, Action.FLAT_ASK, TUE)
        msg = store.track_message(WEEK, MessageKind.FLAT_POLL, "flat-group", BOT, 1_000)
        store.set_reaction(msg, "+49alice", "👍", TUE)

    with Store(path) as store:
        assert store.has_action(WEEK, Action.FLAT_ASK)
        assert store.tracked_message(WEEK, MessageKind.FLAT_POLL) == msg
        assert store.reactions_for(msg) == [Reaction("+49alice", "👍", TUE)]


def test_schema_version_is_set(tmp_path: Path) -> None:
    path = tmp_path / "odib.sqlite"
    Store(path).close()
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)


def test_newer_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "odib.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.close()
    with pytest.raises(RuntimeError, match="newer"):
        Store(path)


def test_upgrade_keeps_old_actions_as_sent(tmp_path: Path) -> None:
    from odib.store import _MIGRATIONS

    path = tmp_path / "odib.db"
    conn = sqlite3.connect(path)
    conn.executescript(f"{_MIGRATIONS[0]}; PRAGMA user_version = 1;")
    conn.execute(
        "INSERT INTO actions VALUES (?, ?, ?)", (WEEK.isoformat(), "flat_ask", TUE.isoformat())
    )
    conn.commit()
    conn.close()
    with Store(path) as store:
        assert store.action_outcome(WEEK, Action.FLAT_ASK) is Outcome.SENT


# --- settings and the setup lock -----------------------------------------------------------------


def test_settings(store: Store) -> None:
    assert store.get_setting("flat_group_id") is None
    store.set_setting("flat_group_id", "group.a=")
    store.set_setting("flat_group_id", "group.b=")
    assert store.get_setting("flat_group_id") == "group.b="
    store.delete_setting("flat_group_id")
    assert store.get_setting("flat_group_id") is None


def test_settings_are_shared_between_connections(tmp_path: Path) -> None:
    path = tmp_path / "odib.db"
    with Store(path) as setup, Store(path) as bot:
        setup.set_setting("dinner_group_id", "group.d=")
        assert bot.get_setting("dinner_group_id") == "group.d="


def test_setup_lock_excludes_a_second_holder(store: Store) -> None:
    assert not store.setup_lock_held(TUE)
    token = store.acquire_setup_lock(TUE)
    assert token is not None
    assert store.setup_lock_held(TUE)
    assert store.acquire_setup_lock(TUE + timedelta(seconds=30)) is None

    store.release_setup_lock(token)
    assert not store.setup_lock_held(TUE)
    assert store.acquire_setup_lock(TUE) is not None


def test_setup_lock_heartbeat_keeps_it_fresh(store: Store) -> None:
    token = store.acquire_setup_lock(TUE)
    assert token is not None
    later = TUE + SETUP_LOCK_TTL - timedelta(seconds=1)
    assert store.refresh_setup_lock(token, later)
    assert store.setup_lock_held(later + SETUP_LOCK_TTL - timedelta(seconds=1))
    assert not store.setup_lock_held(later + SETUP_LOCK_TTL)


def test_stale_setup_lock_is_taken_over(store: Store) -> None:
    old = store.acquire_setup_lock(TUE)
    assert old is not None
    later = TUE + SETUP_LOCK_TTL
    assert not store.setup_lock_held(later)
    new = store.acquire_setup_lock(later)
    assert new is not None

    # The old holder can neither renew nor release the lock it lost.
    assert not store.refresh_setup_lock(old, later)
    store.release_setup_lock(old)
    assert store.setup_lock_held(later)
    assert store.refresh_setup_lock(new, later)


def test_setup_lock_across_connections(tmp_path: Path) -> None:
    path = tmp_path / "odib.db"
    with Store(path) as setup, Store(path) as bot:
        token = setup.acquire_setup_lock(TUE)
        assert token is not None
        assert bot.setup_lock_held(TUE)
        assert bot.acquire_setup_lock(TUE) is None
        setup.release_setup_lock(token)
        assert not bot.setup_lock_held(TUE)


def test_upgrade_from_version_2_adds_settings(tmp_path: Path) -> None:
    from odib.store import _MIGRATIONS

    path = tmp_path / "odib.db"
    conn = sqlite3.connect(path)
    conn.executescript(f"{_MIGRATIONS[0]}; {_MIGRATIONS[1]}; PRAGMA user_version = 2;")
    conn.close()
    with Store(path) as store:
        store.set_setting("flat_group_id", "group.a=")
        assert store.get_setting("flat_group_id") == "group.a="
