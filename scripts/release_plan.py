"""Decide whether a push to main is released, and as which version.

Run by .github/workflows/release.yml on every push to main. Stdlib only; needs `git` (with tags
fetched) and `gh` (authenticated via GH_TOKEN). Writes `release`, `version` and `create_tag` to
$GITHUB_OUTPUT.

Rules (see the "Release" section in CLAUDE.md):

- The bump of a commit comes from the `release:*` label of the PR it was merged from: none ->
  minor, `release:major`, `release:patch`, `release:none` (no release). A commit without a PR is a
  minor release.
- The release covers every first-parent commit since the latest `vX.Y.Z` tag and uses the largest
  bump among them. Normally that is just the merge commit; if a workflow run was skipped (the
  concurrency group only keeps the newest pending run), its commit is folded into the next release
  without losing its label.
- Without any `v*` tag the release is v0.1.0, unless the commit is `release:none`.
- If the commit already carries the latest tag (re-run), that version is reused.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from enum import IntEnum

TAG_RE = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
FIRST_VERSION = (0, 1, 0)

Version = tuple[int, int, int]


class Bump(IntEnum):
    NONE = 0
    PATCH = 1
    MINOR = 2
    MAJOR = 3


LABELS = {
    "release:major": Bump.MAJOR,
    "release:patch": Bump.PATCH,
    "release:none": Bump.NONE,
}


def parse_tag(tag: str) -> Version | None:
    match = TAG_RE.match(tag)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return (major, minor, patch)


def format_version(version: Version) -> str:
    return ".".join(str(part) for part in version)


def latest_tag(tags: list[str]) -> str | None:
    versions = [(parsed, tag) for tag in tags if (parsed := parse_tag(tag)) is not None]
    return max(versions)[1] if versions else None


def bump_for_labels(labels: list[str]) -> Bump:
    """Bump for a merged PR. Raises ValueError on conflicting release labels."""
    release_labels = sorted({label for label in labels if label.startswith("release:")})
    if len(release_labels) > 1:
        raise ValueError(f"conflicting release labels: {', '.join(release_labels)}")
    if not release_labels:
        return Bump.MINOR
    if release_labels[0] not in LABELS:
        raise ValueError(f"unknown release label: {release_labels[0]}")
    return LABELS[release_labels[0]]


def next_version(latest: Version | None, bumps: list[Bump]) -> Version | None:
    """Version to release for `bumps` on top of `latest`, or None if nothing is released."""
    bump = max(bumps, default=Bump.NONE)
    if bump is Bump.NONE:
        return None
    if latest is None:
        return FIRST_VERSION
    major, minor, patch = latest
    if bump is Bump.MAJOR:
        return (major + 1, 0, 0)
    if bump is Bump.MINOR:
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def _run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def _bump_for_commit(repo: str, sha: str) -> Bump:
    pulls = json.loads(_run("gh", "api", f"repos/{repo}/commits/{sha}/pulls"))
    merged = [pull for pull in pulls if pull.get("merged_at")]
    if not merged:
        print(f"{sha[:7]}: no merged PR -> minor")
        return Bump.MINOR
    pull = merged[0]
    labels = [label["name"] for label in pull["labels"]]
    bump = bump_for_labels(labels)
    print(f"{sha[:7]}: PR #{pull['number']} {labels} -> {bump.name.lower()}")
    return bump


def plan(repo: str, sha: str) -> tuple[str | None, bool]:
    """Return (version to release or None, whether the tag still has to be created)."""
    tag = latest_tag(_run("git", "tag", "--list", "v*").split())
    if tag is not None and _run("git", "rev-list", "-n", "1", tag) == sha:
        print(f"{sha[:7]} is already tagged {tag}; re-releasing it")
        return tag.removeprefix("v"), False
    if tag is None:
        # First release: only the merged commit's label matters (release:none or not).
        commits = [sha]
    else:
        commits = _run("git", "rev-list", "--first-parent", f"{tag}..{sha}").split()
        if not commits:
            print(f"{sha[:7]} is already part of {tag}; nothing to release")
            return None, False
    bumps = [_bump_for_commit(repo, commit) for commit in commits]
    version = next_version(parse_tag(tag) if tag else None, bumps)
    if version is None:
        print("only release:none changes; nothing to release")
        return None, False
    print(f"{tag or 'no tag'} -> v{format_version(version)}")
    return format_version(version), True


def main() -> int:
    version, create_tag = plan(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"])
    outputs = {
        "release": str(version is not None).lower(),
        "version": version or "",
        "create_tag": str(create_tag).lower(),
    }
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        out.writelines(f"{key}={value}\n" for key, value in outputs.items())
    return 0


if __name__ == "__main__":
    sys.exit(main())
