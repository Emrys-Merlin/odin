"""Pure version logic of scripts/release_plan.py (the git/gh parts run only in CI)."""

import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).parent.parent / "scripts" / "release_plan.py"
_spec = importlib.util.spec_from_file_location("release_plan", _PATH)
assert _spec is not None and _spec.loader is not None
release_plan = importlib.util.module_from_spec(_spec)
sys.modules["release_plan"] = release_plan
_spec.loader.exec_module(release_plan)

Bump = release_plan.Bump


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("v0.1.0", (0, 1, 0)),
        ("v12.3.45", (12, 3, 45)),
        ("0.1.0", None),
        ("v1.2", None),
        ("v1.2.3-rc1", None),
        ("v01.2.3", None),
    ],
)
def test_parse_tag(tag, expected) -> None:
    assert release_plan.parse_tag(tag) == expected


def test_latest_tag_sorts_numerically_and_ignores_other_tags() -> None:
    tags = ["v0.9.0", "v0.10.0", "v0.2.5", "nightly", "v1.0.0-rc1"]
    assert release_plan.latest_tag(tags) == "v0.10.0"
    assert release_plan.latest_tag(["nightly"]) is None


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        ([], Bump.MINOR),
        (["bug", "documentation"], Bump.MINOR),
        (["release:major"], Bump.MAJOR),
        (["release:patch", "bug"], Bump.PATCH),
        (["release:none"], Bump.NONE),
    ],
)
def test_bump_for_labels(labels, expected) -> None:
    assert release_plan.bump_for_labels(labels) is expected


@pytest.mark.parametrize("labels", [["release:major", "release:patch"], ["release:typo"]])
def test_bump_for_labels_rejects_conflicting_or_unknown_labels(labels) -> None:
    with pytest.raises(ValueError):
        release_plan.bump_for_labels(labels)


@pytest.mark.parametrize(
    ("bumps", "expected"),
    [
        ([Bump.MINOR], (0, 4, 0)),
        ([Bump.PATCH], (0, 3, 2)),
        ([Bump.MAJOR], (1, 0, 0)),
        ([Bump.NONE], None),
        ([], None),
        # A skipped run folds its commit into the next release with the largest bump.
        ([Bump.PATCH, Bump.NONE, Bump.MAJOR], (1, 0, 0)),
        ([Bump.NONE, Bump.PATCH], (0, 3, 2)),
    ],
)
def test_next_version(bumps, expected) -> None:
    assert release_plan.next_version((0, 3, 1), bumps) == expected


@pytest.mark.parametrize("bump", [Bump.MAJOR, Bump.MINOR, Bump.PATCH])
def test_first_release_is_0_1_0_regardless_of_bump(bump) -> None:
    assert release_plan.next_version(None, [bump]) == (0, 1, 0)


def test_first_release_is_skipped_for_release_none() -> None:
    assert release_plan.next_version(None, [Bump.NONE]) is None
