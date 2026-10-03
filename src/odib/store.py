"""SQLite persistence for the weekly dinner cycle.

Everything is keyed by the dinner week, identified by the date of its Sunday. The store holds

- the **actions** performed per week (so nothing is ever sent twice),
- the **tracked messages** whose reactions matter (flat poll, dinner announcement),
- the current **reactions** on those messages.

A Signal message is identified by its author and its (millisecond) Signal timestamp, which is also
how incoming reactions refer to their target message.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
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


class MessageKind(StrEnum):
    """A message the bot sent and whose reactions it tracks."""

    FLAT_POLL = "flat_poll"
    DINNER_ANNOUNCEMENT = "dinner_announcement"


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
)

SCHEMA_VERSION = len(_MIGRATIONS)


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

    # Actions

    def record_action(self, week: date, action: Action, performed_at: datetime) -> bool:
        """Record that ``action`` was performed for ``week``.

        Returns False (and keeps the original timestamp) if it was already recorded.
        """
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO actions (week, action, performed_at) VALUES (?, ?, ?)",
            (week.isoformat(), action.value, _utc(performed_at)),
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


def _message(row: tuple[str, str, str, str, int]) -> TrackedMessage:
    week, kind, group_id, author, timestamp = row
    return TrackedMessage(date.fromisoformat(week), MessageKind(kind), group_id, author, timestamp)
