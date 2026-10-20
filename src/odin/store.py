"""SQLite persistence for the weekly dinner cycle.

Everything is keyed by the dinner week, identified by the date of its Sunday. The store holds

- the **actions** performed per week (so nothing is ever sent twice),
- the **tracked messages** whose reactions matter (flat poll, dinner announcement, the
  confirmation request of `/cancel`),
- the current **reactions** on those messages,
- **settings** chosen at setup time (e.g. the group IDs) and the **setup lock**,
- config **overrides** made via chat, applied on top of the TOML config (see `odin.overrides`),
- the **dropped weeks**: dinner weeks cut short by a new dinner weekday, and when that switch took
  effect (see `odin.engine.transition`),
- the **applied dinner**: the dinner time the weeks are currently run under, and a dinner week a
  new weekday from the config file waits for (see `odin.overrides.effective_config`),
- the **skip dates**: dinner days set via `/skip` on which there is no dinner (see
  `odin.commands.skip`).

A Signal message is identified by its author and its (millisecond) Signal timestamp, which is also
how incoming reactions refer to their target message.
"""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Self


class Action(StrEnum):
    """A step of the weekly cycle that, once performed, must not be repeated."""

    FLAT_ASK = "flat_ask"
    NUDGE = "nudge"
    ANNOUNCEMENT = "announcement"
    CANCELLATION = "cancellation"
    TALLY = "tally"
    # Told the flat group that a tracked message went out but cannot be tracked (see
    # `odin.notices`). The retry of the flat ask is the week's flat poll from then on.
    FLAT_ASK_RETRY = "flat_ask_retry"
    ANNOUNCEMENT_NOTICE = "announcement_notice"


class Outcome(StrEnum):
    """What became of a recorded action."""

    SENT = "sent"
    SKIPPED = "skipped"  # deliberately not sent: too late, or not needed (e.g. no nudge)


class MessageKind(StrEnum):
    """A message the bot sent and whose reactions it tracks."""

    FLAT_POLL = "flat_poll"
    DINNER_ANNOUNCEMENT = "dinner_announcement"
    CANCEL_REQUEST = "cancel_request"  # ODIN's reply to /cancel; a reaction confirms it


@dataclass(frozen=True, slots=True)
class TrackedMessage:
    week: date
    kind: MessageKind
    group_id: str
    author: str
    timestamp: int


@dataclass(frozen=True, slots=True)
class Reaction:
    reactor: str
    emoji: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class Override:
    """A config value changed via chat; `key` and `value` are as in `odin.overrides`."""

    key: str
    value: str
    changed_by: str  # the sender's name if known, else their number
    changed_at: datetime
    # Set for a change that waits for a dinner week to end (a new dinner weekday): it takes effect
    # once the dinner of week `after_week` has started. None: in effect right away.
    after_week: date | None = None


@dataclass(frozen=True, slots=True)
class AppliedDinner:
    """The dinner time the dinner weeks are run under, as an override value (``"sun 18:00"``).

    `held_week` is set while a new dinner weekday from the config file waits for that dinner week
    to end: the weeks keep `point` until its dinner starts.
    """

    point: str
    held_week: date | None = None


@dataclass(frozen=True, slots=True)
class SkipDate:
    """A dinner day without dinner, set via `/skip`: the dinner week `day` is cancelled."""

    day: date
    added_by: str  # the sender's name if known, else their number
    added_at: datetime


# Migration i brings the schema from user_version i to i + 1. Only ever append.
_MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE actions (
        week         TEXT NOT NULL,
        action       TEXT NOT NULL,
        performed_at TEXT NOT NULL,
        PRIMARY KEY (week, action)
    );
    CREATE TABLE messages (
        week      TEXT NOT NULL,
        kind      TEXT NOT NULL,
        group_id  TEXT NOT NULL,
        author    TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        PRIMARY KEY (week, kind),
        UNIQUE (author, timestamp)
    );
    CREATE TABLE reactions (
        msg_author    TEXT NOT NULL,
        msg_timestamp INTEGER NOT NULL,
        reactor       TEXT NOT NULL,
        emoji         TEXT NOT NULL,
        received_at   TEXT NOT NULL,
        PRIMARY KEY (msg_author, msg_timestamp, reactor),
        FOREIGN KEY (msg_author, msg_timestamp)
            REFERENCES messages (author, timestamp) ON DELETE CASCADE
    );
    """,
    """
    ALTER TABLE actions ADD COLUMN outcome TEXT NOT NULL DEFAULT 'sent';
    """,
    """
    CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE overrides (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        changed_by TEXT NOT NULL,
        changed_at TEXT NOT NULL
    );
    """,
    """
    ALTER TABLE overrides ADD COLUMN after_week TEXT;
    """,
    """
    CREATE TABLE dropped_weeks (
        week   TEXT PRIMARY KEY,
        switch TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE applied_dinner (
        id        INTEGER PRIMARY KEY CHECK (id = 1),
        point     TEXT NOT NULL,
        held_week TEXT
    );
    """,
    """
    CREATE TABLE skip_dates (
        day      TEXT PRIMARY KEY,
        added_by TEXT NOT NULL,
        added_at TEXT NOT NULL
    );
    """,
)

SCHEMA_VERSION = len(_MIGRATIONS)

_SETUP_LOCK = "setup_lock"
# A setup lock whose heartbeat is older than this is stale: its holder is gone.
SETUP_LOCK_TTL = timedelta(minutes=2)


def _utc(moment: datetime) -> str:
    """Serialise as UTC, so stored timestamps sort chronologically as text."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"naive datetime not allowed: {moment!r}")
    return moment.astimezone(UTC).isoformat()


class Store:
    """SQLite-backed state. Pass ``":memory:"`` for a throwaway database."""

    def __init__(self, path: str | Path) -> None:
        self._conn = sqlite3.connect(path, autocommit=True)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _migrate(self) -> None:
        (version,) = self._conn.execute("PRAGMA user_version").fetchone()
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"database schema version {version} is newer than supported ({SCHEMA_VERSION})"
            )
        for target, script in enumerate(_MIGRATIONS[version:], start=version + 1):
            # executescript commits on its own, so wrap the migration explicitly.
            self._conn.executescript(f"BEGIN; {script}; PRAGMA user_version = {target}; COMMIT;")

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Apply the writes inside the block all together or not at all."""
        self._conn.execute("BEGIN")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    # Actions

    def record_action(
        self,
        week: date,
        action: Action,
        performed_at: datetime,
        outcome: Outcome = Outcome.SENT,
    ) -> bool:
        """Record that ``action`` was performed (or deliberately skipped) for ``week``.

        Returns False (and keeps the original record) if it was already recorded.
        """
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO actions (week, action, performed_at, outcome)"
            " VALUES (?, ?, ?, ?)",
            (week.isoformat(), action.value, _utc(performed_at), outcome.value),
        )
        return cursor.rowcount == 1

    def has_action(self, week: date, action: Action) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM actions WHERE week = ? AND action = ?",
            (week.isoformat(), action.value),
        ).fetchone()
        return row is not None

    def action_time(self, week: date, action: Action) -> datetime | None:
        row = self._conn.execute(
            "SELECT performed_at FROM actions WHERE week = ? AND action = ?",
            (week.isoformat(), action.value),
        ).fetchone()
        return None if row is None else datetime.fromisoformat(row[0])

    def latest_week_before(self, week: date) -> date | None:
        """The latest week before ``week`` with a recorded action; None if there is none."""
        (latest,) = self._conn.execute(
            "SELECT max(week) FROM actions WHERE week < ?", (week.isoformat(),)
        ).fetchone()
        return None if latest is None else date.fromisoformat(latest)

    def unfinished_weeks_before(self, week: date) -> list[date]:
        """The weeks before ``week`` that were started (anything recorded) or dropped, but whose
        tally, the last step of every week, is not recorded yet; oldest first."""
        rows = self._conn.execute(
            "SELECT week FROM actions WHERE week < :week"
            " UNION SELECT week FROM dropped_weeks WHERE week < :week"
            " EXCEPT SELECT week FROM actions WHERE action = :tally"
            " ORDER BY week",
            {"week": week.isoformat(), "tally": Action.TALLY.value},
        ).fetchall()
        return [date.fromisoformat(w) for (w,) in rows]

    def has_any_action(self, week: date) -> bool:
        """Whether anything is recorded for ``week``."""
        row = self._conn.execute("SELECT 1 FROM actions WHERE week = ?", (week.isoformat(),))
        return row.fetchone() is not None

    def action_outcome(self, week: date, action: Action) -> Outcome | None:
        """Whether ``action`` was sent or skipped for ``week``; None if not recorded yet."""
        row = self._conn.execute(
            "SELECT outcome FROM actions WHERE week = ? AND action = ?",
            (week.isoformat(), action.value),
        ).fetchone()
        return None if row is None else Outcome(row[0])

    # Tracked messages

    def track_message(
        self, week: date, kind: MessageKind, group_id: str, author: str, timestamp: int
    ) -> TrackedMessage:
        """Start tracking a sent message. Each week has at most one message per kind."""
        self._conn.execute(
            "INSERT INTO messages (week, kind, group_id, author, timestamp) VALUES (?, ?, ?, ?, ?)",
            (week.isoformat(), kind.value, group_id, author, timestamp),
        )
        return TrackedMessage(week, kind, group_id, author, timestamp)

    def tracked_message(self, week: date, kind: MessageKind) -> TrackedMessage | None:
        row = self._conn.execute(
            "SELECT week, kind, group_id, author, timestamp FROM messages"
            " WHERE week = ? AND kind = ?",
            (week.isoformat(), kind.value),
        ).fetchone()
        return None if row is None else _message(row)

    def find_message(self, author: str, timestamp: int) -> TrackedMessage | None:
        """Look up a tracked message the way an incoming reaction refers to it."""
        row = self._conn.execute(
            "SELECT week, kind, group_id, author, timestamp FROM messages"
            " WHERE author = ? AND timestamp = ?",
            (author, timestamp),
        ).fetchone()
        return None if row is None else _message(row)

    # Reactions

    def set_reaction(
        self, message: TrackedMessage, reactor: str, emoji: str, received_at: datetime
    ) -> None:
        """Store a reaction; it replaces the reactor's previous one (one per person in Signal)."""
        self._conn.execute(
            "INSERT INTO reactions (msg_author, msg_timestamp, reactor, emoji, received_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (msg_author, msg_timestamp, reactor)"
            " DO UPDATE SET emoji = excluded.emoji, received_at = excluded.received_at",
            (message.author, message.timestamp, reactor, emoji, _utc(received_at)),
        )

    def remove_reaction(
        self, message: TrackedMessage, reactor: str, emoji: str | None = None
    ) -> bool:
        """Delete the reactor's reaction. Returns whether one was removed.

        If ``emoji`` is given, only a reaction with that emoji is removed, so a stale removal
        (for an emoji that was already replaced) does not drop the current reaction.
        """
        query = "DELETE FROM reactions WHERE msg_author = ? AND msg_timestamp = ? AND reactor = ?"
        params: tuple[str | int, ...] = (message.author, message.timestamp, reactor)
        if emoji is not None:
            query += " AND emoji = ?"
            params += (emoji,)
        return self._conn.execute(query, params).rowcount == 1

    def reactions_for(self, message: TrackedMessage) -> list[Reaction]:
        """Current reactions on ``message``, oldest first."""
        rows = self._conn.execute(
            "SELECT reactor, emoji, received_at FROM reactions"
            " WHERE msg_author = ? AND msg_timestamp = ? ORDER BY received_at, reactor",
            (message.author, message.timestamp),
        ).fetchall()
        return [Reaction(r, e, datetime.fromisoformat(t)) for r, e, t in rows]

    # Settings

    def get_setting(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return None if row is None else row[0]

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def delete_setting(self, key: str) -> None:
        self._conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    # Config overrides

    def set_override(
        self,
        key: str,
        value: str,
        changed_by: str,
        now: datetime,
        after_week: date | None = None,
    ) -> None:
        """Store an override; it replaces an earlier one for the same key."""
        self._conn.execute(
            "INSERT INTO overrides (key, value, changed_by, changed_at, after_week)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value,"
            " changed_by = excluded.changed_by, changed_at = excluded.changed_at,"
            " after_week = excluded.after_week",
            (
                key,
                value,
                changed_by,
                _utc(now),
                None if after_week is None else after_week.isoformat(),
            ),
        )

    def delete_override(self, key: str) -> bool:
        """Drop the override for ``key``. Returns whether there was one."""
        return self._conn.execute("DELETE FROM overrides WHERE key = ?", (key,)).rowcount == 1

    def overrides(self) -> dict[str, Override]:
        """All overrides by key, oldest change first."""
        rows = self._conn.execute(
            "SELECT key, value, changed_by, changed_at, after_week FROM overrides"
            " ORDER BY changed_at, key"
        ).fetchall()
        return {
            k: Override(
                k,
                v,
                by,
                datetime.fromisoformat(at),
                None if after is None else date.fromisoformat(after),
            )
            for k, v, by, at, after in rows
        }

    # Dropped weeks

    def record_dropped_week(self, week: date, switch: datetime) -> bool:
        """Record that dinner week ``week`` is dropped by a dinner weekday change at ``switch``.

        Returns False (and keeps the original record) if it was already recorded.
        """
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO dropped_weeks (week, switch) VALUES (?, ?)",
            (week.isoformat(), _utc(switch)),
        )
        return cursor.rowcount == 1

    def dropped_at(self, week: date) -> datetime | None:
        """When the switch that dropped ``week`` took effect; None if ``week`` is not dropped."""
        row = self._conn.execute(
            "SELECT switch FROM dropped_weeks WHERE week = ?", (week.isoformat(),)
        ).fetchone()
        return None if row is None else datetime.fromisoformat(row[0])

    def delete_dropped_week(self, week: date) -> bool:
        """Forget that ``week`` is dropped. Returns whether it was recorded as dropped."""
        cursor = self._conn.execute("DELETE FROM dropped_weeks WHERE week = ?", (week.isoformat(),))
        return cursor.rowcount == 1

    # Applied dinner

    def applied_dinner(self) -> AppliedDinner | None:
        """The dinner the weeks are run under; None until it is first stored."""
        row = self._conn.execute("SELECT point, held_week FROM applied_dinner").fetchone()
        if row is None:
            return None
        point, held = row
        return AppliedDinner(point, None if held is None else date.fromisoformat(held))

    def set_applied_dinner(self, point: str, held_week: date | None = None) -> None:
        """Store the dinner the weeks are run under; replaces the previous one."""
        self._conn.execute(
            "INSERT INTO applied_dinner (id, point, held_week) VALUES (1, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET point = excluded.point,"
            " held_week = excluded.held_week",
            (point, None if held_week is None else held_week.isoformat()),
        )

    # Skip dates

    def add_skip_date(self, day: date, added_by: str, now: datetime) -> bool:
        """Record that there is no dinner on ``day``.

        Returns False (and keeps the original record) if it was already recorded.
        """
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO skip_dates (day, added_by, added_at) VALUES (?, ?, ?)",
            (day.isoformat(), added_by, _utc(now)),
        )
        return cursor.rowcount == 1

    def delete_skip_date(self, day: date) -> bool:
        """Forget the skip date ``day``. Returns whether it was recorded."""
        cursor = self._conn.execute("DELETE FROM skip_dates WHERE day = ?", (day.isoformat(),))
        return cursor.rowcount == 1

    def skip_date(self, day: date) -> SkipDate | None:
        """The skip date ``day``; None if there is none."""
        row = self._conn.execute(
            "SELECT day, added_by, added_at FROM skip_dates WHERE day = ?", (day.isoformat(),)
        ).fetchone()
        return None if row is None else _skip_date(row)

    def skip_dates(self, since: date | None = None) -> list[SkipDate]:
        """The skip dates on or after ``since`` (all if None), earliest first."""
        rows = self._conn.execute(
            "SELECT day, added_by, added_at FROM skip_dates WHERE day >= ? ORDER BY day",
            ("" if since is None else since.isoformat(),),
        ).fetchall()
        return [_skip_date(row) for row in rows]

    # Setup lock: held by `odin setup` while it runs, so `odin run` stays out of its way. It is
    # a settings row "<token> <heartbeat>"; the holder refreshes the heartbeat, and a lock whose
    # heartbeat is older than SETUP_LOCK_TTL is stale, so a killed holder cannot block forever.

    def acquire_setup_lock(self, now: datetime) -> str | None:
        """Take the setup lock. Returns the holder's token, or None if it is held elsewhere."""
        token = secrets.token_hex(8)
        # IMMEDIATE takes the write lock up front, so two processes cannot both see it free.
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            if self._setup_lock_fresh(now):
                return None
            self.set_setting(_SETUP_LOCK, f"{token} {_utc(now)}")
        finally:
            self._conn.execute("COMMIT")
        return token

    def refresh_setup_lock(self, token: str, now: datetime) -> bool:
        """Renew the heartbeat. Returns False if `token` no longer holds the lock."""
        cursor = self._conn.execute(
            "UPDATE settings SET value = ? WHERE key = ? AND value LIKE ?",
            (f"{token} {_utc(now)}", _SETUP_LOCK, f"{token} %"),
        )
        return cursor.rowcount == 1

    def release_setup_lock(self, token: str) -> None:
        """Release the lock if `token` holds it; a lock taken over by someone else stays."""
        self._conn.execute(
            "DELETE FROM settings WHERE key = ? AND value LIKE ?", (_SETUP_LOCK, f"{token} %")
        )

    def setup_lock_held(self, now: datetime) -> bool:
        """Whether someone holds a fresh setup lock at `now`."""
        return self._setup_lock_fresh(now)

    def _setup_lock_fresh(self, now: datetime) -> bool:
        value = self.get_setting(_SETUP_LOCK)
        if value is None:
            return False
        _, _, heartbeat = value.partition(" ")
        try:
            beat = datetime.fromisoformat(heartbeat)
        except ValueError:
            return False  # unreadable: treat as stale
        return datetime.fromisoformat(_utc(now)) - beat < SETUP_LOCK_TTL


def _message(row: tuple[str, str, str, str, int]) -> TrackedMessage:
    week, kind, group_id, author, timestamp = row
    return TrackedMessage(date.fromisoformat(week), MessageKind(kind), group_id, author, timestamp)


def _skip_date(row: tuple[str, str, str]) -> SkipDate:
    day, added_by, added_at = row
    return SkipDate(date.fromisoformat(day), added_by, datetime.fromisoformat(added_at))
