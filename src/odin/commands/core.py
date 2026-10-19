"""The command interface: what a command gets, what it returns, and how a message is parsed.

Commands are pure functions over a `CommandContext`; they never talk to Signal. A command module
imports `Command`, `CommandContext` and `CommandError` from here rather than from `odin.commands`,
which imports the command modules for its registry.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Self

from odin.config import Config
from odin.store import MessageKind, Store


@dataclass(frozen=True)
class CommandContext:
    """Everything a command may look at. Commands that change settings write to `store`."""

    base: Config  # TOML only (needed to validate/reset overrides)
    config: Config  # effective config (TOML + overrides)
    store: Store
    now: datetime
    sender: str  # number or UUID
    sender_name: str | None


class TrackedReply(str):
    """A reply whose reactions matter: once sent, it is tracked as message `kind` of `week`.

    Otherwise it is a plain string, so commands keep returning ``list[str]``. A week has at most
    one tracked message per kind; a later one is sent but not tracked (see `odin.events`).
    """

    week: date
    kind: MessageKind

    def __new__(cls, text: str, week: date, kind: MessageKind) -> Self:
        reply = super().__new__(cls, text)
        reply.week = week
        reply.kind = kind
        return reply


class CommandError(Exception):
    """Its message is a German text shown to the user as the reply."""


@dataclass(frozen=True)
class Command:
    name: str  # "schedule"
    usage: str  # "/schedule" or "/settime <punkt> <tag> <HH:MM>"
    summary: str  # German one-liner for /help
    run: Callable[[CommandContext, str], list[str]]  # args → replies (one Signal message each)


@dataclass(frozen=True)
class Invocation:
    """A message that is a command."""

    word: str  # the command word as typed, prefix included ("!Help"), for error messages
    name: str  # lower case ("help"); "" if the word is not only letters ("/help2")
    args: str  # everything after the word, surrounding whitespace stripped, newlines kept


# A prefix followed by a letter makes a command. The command word runs up to the first whitespace;
# if it holds more than letters ("/help2", "/settext:"), it is an unknown command, not "help".
_COMMAND = re.compile(r"\s*([/!][a-z]\S*)(.*)", re.IGNORECASE | re.DOTALL)
_NAME = re.compile(r"[a-z]+")


def parse(text: str) -> Invocation | None:
    """Split a message into command word and args; None if it is not a command."""
    match = _COMMAND.fullmatch(text)
    if match is None:
        return None
    word, args = match.groups()
    name = word[1:].lower()
    return Invocation(word=word, name=name if _NAME.fullmatch(name) else "", args=args.strip())
