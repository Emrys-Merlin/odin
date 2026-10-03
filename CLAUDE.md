# CLAUDE.md

ODIN (repo `odib`) is a Signal bot for our weekly open Sunday dinner. Goals, the weekly cycle and
the architecture are in `docs/GOALS.md` — read it before starting an issue.

## Workflow

- Work is tracked in GitHub issues (`gh issue view <n>`). Work on exactly one issue per session.
- Branch from `main`; any branch name is fine (cloud sessions use `claude/<slug>`). Open a PR with
  `Closes #<n>`. Never push to `main`.
- Things found outside the issue's scope: note them in the PR description or open a new issue —
  do not fix them in the same PR.
- If an issue's description turns out wrong or incomplete, say so in the PR rather than silently
  deviating.

## Release

Every merge to `main` is a release `vX.Y.Z` (git tag, GitHub Release, image on GHCR); the tag is
the only source of the version. The bump comes from the PR's label — set at most one:

| Label | Bump |
|---|---|
| *(none)* | minor (default) |
| `release:major` | major — reserved for going live (`1.0.0`) and breaking changes after that |
| `release:patch` | patch — hotfixes |
| `release:none` | nothing released, no image pushed — docs-only, CI-only, … |

Never create `v*` tags or edit `version` by hand; `.github/workflows/release.yml` does it.

## Commands

Everything goes through uv; do not use pip or ad-hoc venvs.

- `uv sync` — install
- `uv run pytest` — tests
- `uv run prek run --all-files` — ruff (lint + format) and ty; the same check CI runs

The prek hook is installed in cloud sessions by `scripts/session-start.sh`.

## Design rules

- The Signal client and the clock are interfaces. Tests use the fake client and a fixed clock;
  no test may touch the network or the real time.
- The scheduler is a reconcile loop over (config, state, now) — never "sleep until Tuesday".
  Every sent action is recorded so nothing is sent twice.
- Message texts live in the config as templates, not in code. Dinner-group texts are bilingual
  (German, then English).
- No secrets in the repo. The phone number comes from an env var; the group IDs are stored in the
  state DB by `odib setup` and can be overridden by env vars.

## Environment

Cloud sessions have no Signal access and no secrets. Anything that needs the real bot (registration,
deployment) is written as a runbook in `docs/` for Tim to execute.
