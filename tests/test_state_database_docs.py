"""docs/reference/state-database.md describes the schema `odin.store` actually creates."""

import re
from pathlib import Path

import pytest

from odin.app import DINNER_GROUP_KEY, FLAT_GROUP_KEY
from odin.overrides import CANCELLATION_ENABLED_KEY, NUDGE_ENABLED_KEY, PENDING_DINNER_KEY
from odin.setup import SETUP_KEYS
from odin.store import _SETUP_LOCK, SCHEMA_VERSION, Action, MessageKind, Outcome, Store

PAGE = (Path(__file__).parent.parent / "docs" / "reference" / "state-database.md").read_text(
    encoding="utf-8"
)


def _schema() -> dict[str, list[str]]:
    """Table -> column names, of a freshly migrated database."""
    with Store(":memory:") as store:
        conn = store._conn
        tables = [
            name
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY rowid"
            )
        ]
        return {t: [row[1] for row in conn.execute(f"PRAGMA table_info({t})")] for t in tables}


SCHEMA = _schema()


def _sections() -> dict[str, str]:
    """Table heading (``### `name` ``) -> the text up to the next heading."""
    parts = re.split(r"^### `(\w+)`$", PAGE, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def _code(value: str) -> str:
    return f"`{value}`"


def test_every_table_has_a_section() -> None:
    assert list(_sections()) == list(SCHEMA)


@pytest.mark.parametrize("table", sorted(SCHEMA))
def test_columns_match(table: str) -> None:
    documented = re.findall(r"^\| `(\w+)` \| `\w+` \|", _sections()[table], flags=re.MULTILINE)
    assert documented == SCHEMA[table]


def test_schema_version() -> None:
    assert f"the current one is **{SCHEMA_VERSION}**" in PAGE
    versions = re.findall(r"^\| (\d+) \|", PAGE, flags=re.MULTILINE)
    assert versions == [str(v) for v in range(1, SCHEMA_VERSION + 1)]


@pytest.mark.parametrize(
    "value",
    [
        *Action,
        *Outcome,
        *MessageKind,
        *SETUP_KEYS,
        FLAT_GROUP_KEY,
        DINNER_GROUP_KEY,
        _SETUP_LOCK,
        NUDGE_ENABLED_KEY,
        CANCELLATION_ENABLED_KEY,
        PENDING_DINNER_KEY,
    ],
)
def test_stored_value_is_listed(value: str) -> None:
    assert _code(value) in PAGE
