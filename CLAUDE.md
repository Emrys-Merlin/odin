# CLAUDE.md

ODIN (repo `odin`) is a Signal bot for our weekly open Sunday dinner. Goals, the weekly cycle and
the architecture are in `docs/explanation/` — read it (at least `design-goals.md`,
`weekly-cycle.md` and `reliability.md`) before starting an issue.

## Workflow

- Work is tracked in GitHub issues (`gh issue view <n>`; milestone **MVP** for the first usable
  version). One issue per vertical slice; each issue is self-contained so a cold Claude Code cloud
  session can pick it up. Work on exactly one issue per session.
- Changes land via PRs that Tim reviews; CI must be green.
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
- `uv run --group docs zensical build --strict` — build the docs site; CI runs it too

The prek hook is installed in cloud sessions by `scripts/session-start.sh`.

## Docs

The docs site (`docs/`, nav in `mkdocs.yml`, published to https://emrys-merlin.github.io/odin/)
follows Diátaxis. Details: `docs/how-to/develop/write-docs.md`.

- Every page is exactly one quadrant: `tutorials/`, `how-to/`, `reference/` or `explanation/`.
- English; German chat texts are quoted verbatim. Facts (syntax, keys, defaults, placeholders)
  live once in `reference/`; other pages link there.
- A PR that changes user-visible behaviour updates the matching docs page in the same PR.
- Chat examples use the chat-mock HTML from `write-docs.md`, built from the real texts.
- Changed the CLI, a chat command or a template placeholder? Rerun `uv run scripts/gen_reference.py`
  (it writes `docs/reference/_generated/`; a test fails while it is stale).

## Design rules

- The Signal client and the clock are interfaces. Tests use the fake client and a fixed clock;
  no test may touch the network or the real time.
- The scheduler is a reconcile loop over (config, state, now) — never "sleep until Tuesday".
  Every sent action is recorded so nothing is sent twice.
- The messages of the weekly cycle live in the config as templates, not in code. Dinner-group
  texts are bilingual (German, then English).
- Chat-command replies (help, errors, previews) are German UI strings in code, in
  `src/odin/commands/`, not config templates. Strings shared by several commands go in
  `commands/ui.py`. Each command is its own module, registered in `commands/__init__.py`.
- No secrets in the repo. The phone number comes from an env var; the group IDs are stored in the
  state DB by `odin setup` and can be overridden by env vars.

## Environment

Cloud sessions have no Signal access and no secrets. Anything that needs the real bot (registration,
deployment) is written as a tutorial or how-to in `docs/` for Tim to execute.

Cloud sessions cannot push changes under `.github/workflows/` (the GitHub connection lacks the
`workflow` scope, so GitHub refuses the push). Do not try. Instead:

1. Commit the workflow change as its own commit(s), separate from everything else.
2. Export it with `git format-patch` into a `.patch` file and hand that file to Tim (send it in the
   session and paste it into the PR description, so it survives the container).
3. Drop those commits from the branch before pushing, and push the rest as usual.
4. Say in the PR that it needs the patch; Tim applies it to the PR branch locally with `git am`.
