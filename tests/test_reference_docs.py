"""The generated reference fragments in docs/reference/_generated/ match the code."""

import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).parent.parent / "scripts" / "gen_reference.py"
_spec = importlib.util.spec_from_file_location("gen_reference", _PATH)
assert _spec is not None
assert _spec.loader is not None
gen_reference = importlib.util.module_from_spec(_spec)
sys.modules["gen_reference"] = gen_reference
_spec.loader.exec_module(gen_reference)

GENERATED = gen_reference.render()


@pytest.mark.parametrize("name", sorted(GENERATED))
def test_generated_reference_is_current(name: str) -> None:
    path = gen_reference.OUT_DIR / name
    committed = path.read_text(encoding="utf-8") if path.exists() else None
    assert committed == GENERATED[name], (
        f"docs/reference/_generated/{name} is stale: run `uv run scripts/gen_reference.py`"
    )


def test_no_stray_generated_files() -> None:
    present = {path.name for path in gen_reference.OUT_DIR.iterdir()}
    assert present == set(GENERATED), "run `uv run scripts/gen_reference.py`"
