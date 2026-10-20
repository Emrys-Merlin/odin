# Run locally

**How-to guide** — steps for one task you already know you want to do.

Install, run the tests and checks, and try ODIN offline. Nothing here needs Signal, a phone
number or secrets.

The rules for working on ODIN (one issue per PR, branches, no pushes to `main`) are in
[`CLAUDE.md`](https://github.com/Emrys-Merlin/odin/blob/main/CLAUDE.md), the entry point for
contributors.

## Install

You need [uv](https://docs.astral.sh/uv/) and git. Everything goes through uv; do not use pip or
an ad-hoc virtualenv.

```sh
git clone https://github.com/Emrys-Merlin/odin.git
cd odin
uv sync                   # installs Python 3.14 (from .python-version) and the dev tools
uv run prek install       # optional: run ruff and ty on every commit
```

`uv run odin --version` should now print a version such as `0.12.1.dev2+g390c83f1a`: it is
derived from the latest `vX.Y.Z` git tag, so a clone without tags shows `0.0.0`-something (see
[Release](release.md)).

## Run the tests and checks

These are the same commands CI runs on every PR:

```sh
uv run pytest                     # all tests, offline, a few seconds
uv run prek run --all-files       # ruff (lint + format) and ty (types)
```

Narrow the tests while you work:

```sh
uv run pytest tests/test_engine.py           # one file
uv run pytest -k nudge                       # tests whose name contains "nudge"
uv run pytest tests/test_engine.py -x -q     # stop at the first failure, short output
```

If `prek` reformatted files, look at the diff, stage it and run it again.

## Drive the weekly cycle in a test

No test touches the network or the real time. The Signal client and the clock are interfaces
([Architecture](../../explanation/architecture.md)), and tests pass fakes:

| Fake | Where | What it does |
|---|---|---|
| `FakeSignalClient` | `src/odin/signal/fake.py` | Records sent group messages in `.sent` (with increasing timestamps), yields events you `inject()`, can make the next sends fail with `fail_sends()`. |
| `FakeSignalAdmin` | `src/odin/signal/fake.py` | The fake client plus the admin calls of `odin setup` (register, verify, groups …); `script()` sets their outcomes, `calls_to()` shows what was called. |
| `FixedClock` | `src/odin/clock.py` | Stands still at a given moment until the test calls `set()`, or until something sleeps on it. Rejects naive datetimes. |

Pick the level that fits what you change:

- **Scheduler and reactions** — `tests/test_engine.py`. Its `Bot` helper calls `reconcile()` at
  times you choose: `bot.tick(now)` once, `bot.run(start, end)` every 15 minutes in between,
  `bot.react(kind, reactor, at=...)` adds a 👍 to a tracked message. `bot.texts()`,
  `bot.log` and `bot.outcomes()` show what was sent and recorded. `local(day, hour)` builds a
  Berlin time in October 2026; `WEEK` is the Sunday of that dinner week. A test reads like a
  week:

  ```python
  def test_confirmed_week_is_announced(bot: Bot) -> None:
      bot.tick(local(6, 18))  # Tue 18:00: flat ask
      bot.react(MessageKind.FLAT_POLL, ANNA, at=local(6, 19))  # Anna confirms
      bot.run(local(6, 19), local(8, 12))  # until Thu 12:00: announcement
      bot.react(MessageKind.DINNER_ANNOUNCEMENT, BEN, at=local(8, 12))  # Ben is coming
      bot.run(local(8, 12), local(9, 15))  # until Fri 15:00: tally
      assert bot.texts() == ["ASK 👍 bis 18:00", "ESSEN 18:00", "TALLY 1 x 👍"]
  ```

  The tests use short dummy templates (`TEMPLATES` at the top of the file), so assertions stay
  readable; `bot.texts()` keeps only the first line of each message.
- **Whole app** — `tests/test_app.py` runs ODIN's main loop with a `FakeSignalClient` and a
  `FixedClock` inside `async with running_bot(store, client, clock):`, injects group messages and
  reactions, and waits with `until(condition)`.
- **Chat commands** — call `handle(text, ctx)` from `odin.commands` with a `CommandContext` on an
  in-memory `Store(":memory:")`; see the `ctx` fixture in `tests/test_commands.py` and
  [Add a chat command](add-a-chat-command.md).
- **Setup** — `tests/test_setup.py` drives `odin setup` with a `FakeSignalAdmin` and a
  `FixedClock`.
- **Signal API shapes** — `tests/fixtures/signal/` holds JSON responses of
  signal-cli-rest-api for the parsing and REST client tests; its `README.md` says where they
  come from.
- **Shared helpers** — `tests/conftest.py` provides the in-memory `store` fixture to every module;
  `tests/helpers.py` has `local(day, hour, minute)` (a moment in October 2026, Berlin time) and
  `ms(moment)` (a Signal timestamp). Import them explicitly: `from helpers import local, ms`.

## Check a config file

`odin check-config` validates a config file and the env vars, and prints the next scheduled
actions. It needs no Signal: give it any number and a database path (a missing database is not
created).

```sh
SIGNAL_NUMBER=+490000000000 ODIN_CONFIG=config.example.toml ODIN_DB=/tmp/odin.db \
  uv run odin check-config
```

You should see something like:

```text
Config OK: config.example.toml
Number:       +490000000000
Flat group:   -
Dinner group: -
Database:     /tmp/odin.db
Timezone:     Europe/Berlin
Emoji:        👍
Not set up yet (no flat and no dinner group chosen) — run: podman exec -it odin odin setup

Next scheduled actions:
  Tue 2026-10-20 18:00  flat ask (flat group)
  Wed 2026-10-21 12:00  nudge (flat group, only if nobody confirmed)
  Wed 2026-10-21 18:00  announcement / cancellation (dinner group)
  Fri 2026-10-23 14:00  tally (flat group, only if dinner is on)
```

A broken config ends with `odin: configuration error: …` and exit code 1. The keys and env vars
are listed in [Configuration](../../reference/configuration.md), the commands in
[CLI](../../reference/cli.md).

`odin run` and `odin setup` need a real signal-cli-rest-api; they are not meant to run in a
development checkout. See [First deployment](../../tutorials/first-deployment.md).

## Build the docs

```sh
uv run --group docs zensical serve            # live preview on http://localhost:8000
uv run --group docs zensical build --strict   # what CI runs; warnings and broken links fail
```

How to write a page: [Write docs](write-docs.md).
