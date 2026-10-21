# Add a chat command

**How-to guide** — steps for one task you already know you want to do.

Add a new `/command`, from module to tests to docs. The worked example is `/version`
(`src/odin/commands/version.py`), the smallest command ODIN has.

Before you start: the design rules for commands (German UI strings in code, one module per
command, shared strings in `ui.py`) are in
[`CLAUDE.md`](https://github.com/Emrys-Merlin/odin/blob/main/CLAUDE.md#design-rules). How to get
a working checkout: [Run locally](run-locally.md).

## 1. Write the module

Create `src/odin/commands/<name>.py`. A command is a `Command` (from `odin.commands.core`) whose
`run` function gets a `CommandContext` and the arguments, and returns the replies. This is the
whole of `/version`:

```python title="src/odin/commands/version.py"
--8 < --"src/odin/commands/version.py"
```

What goes where:

- **Docstring** — the first line names the command and says what it does.
- **German strings** — module-level constants (`REPLY` above), formatted in `run`. A string
  that several commands use goes into `src/odin/commands/ui.py` instead (for example
  `ui.HELP_HINT`, `ui.weekly_time()`, `ui.override_marker()`).
- **`run(ctx, args)`** — `args` is everything after the command word, stripped, newlines kept
  (`/settext` reads its template from the following lines). Return a `list[str]`; each string is
  sent as one Signal message to the flat group (or back to the sender of a direct message). Return `[]` to send nothing.
- **The `Command`** — `name` is the lower-case word after `/` or `!` (letters only); `usage`
  is how `/help` shows it, with German argument names (`/settime <punkt> <tag> <HH:MM>`);
  `summary` is the German one-liner `/help` prints after it.
- **`changes=True`** — set it on a command that changes settings or state. Sent in a
  [direct message](../../reference/chat-commands.md#direct-messages), it then gets the notice to
  the flat group, if it wrote anything to the store. A command that only shows something leaves
  it unset.
- **`group_only=True`** — set it on a command that returns a `TrackedReply`: a confirmation by
  reaction counts only in the flat group, so the command is refused in a direct message before
  it runs.

The `CommandContext` (`src/odin/commands/core.py`) holds everything a command may look at:

| Field | What |
|---|---|
| `config` | The effective config: config file plus chat changes. Use it to show values. |
| `base` | The config file alone. Use it to validate or reset a chat change. |
| `store` | The state DB. Commands that change settings write their overrides here. |
| `now` | The current time, from the clock — never call `datetime.now()`. |
| `sender`, `sender_name` | Who sent the command (number or UUID, and the profile name if known). |
| `direct` | Whether it came in a direct message rather than the flat group. Most commands ignore it. |

Commands never talk to Signal; ODIN sends what `run` returns.

**Errors the user caused** (a wrong argument, a change that is not allowed now): raise
`CommandError("…")` with a German message. It is sent as the reply. Any other exception is
logged and answered with `ui.GENERIC_ERROR` ("Da ist etwas schiefgegangen – bitte später nochmal
versuchen."), so do not catch broad exceptions just to hide them.

**A reply whose reactions matter** (like the confirmation request of `/cancel`): return a
`TrackedReply(text, week, kind)` instead of a plain string. Once sent, ODIN tracks it as message
`kind` of that dinner week, so reactions on it are counted. See `src/odin/commands/cancel.py`.

## 2. Register it

Import the `Command` in `src/odin/commands/__init__.py` and add it to `COMMANDS`, one line per
command. The order of `COMMANDS` is the order `/help` lists the commands, so put it next to the
commands it belongs with:

```python title="src/odin/commands/__init__.py"
from odin.commands.version import VERSION
...
COMMANDS: list[Command] = [
    HELP,
    ...
    CANCEL,
    VERSION,
]
```

That is all the wiring: `/help` lists it, and `/name` and `!name` (in any case) run it in the
flat group and, for allowed senders, in a direct message.

## 3. Test it

Add `tests/test_command_<name>.py`. Drive the command through `handle()`, the same entry point
ODIN uses, so the test covers parsing and registration too. Copy the `ctx` fixture from
`tests/test_command_version.py`: a minimal config from `parse_config()`, an in-memory store and a
fixed `NOW`.

```python title="tests/test_command_version.py (excerpt)"
@pytest.mark.parametrize("text", ["/version", "!version", "/VERSION", "/version egal"])
def test_version_replies_with_the_running_version(
    ctx: CommandContext, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    monkeypatch.setattr(odin, "__version__", "1.2.3")
    assert handle(text, ctx) == ["Odin 🍽️ läuft in Version 1.2.3."]


def test_help_lists_version(ctx: CommandContext) -> None:
    [reply] = handle("/help", ctx)
    assert "/version – Zeigt, welche Version von Odin läuft." in reply.splitlines()
```

Cover at least: the happy path with the exact German reply, each `CommandError`, what the command
writes to the store (if anything), and that `/help` lists it. A command that depends on the
dinner week takes `now` from `ctx`; give the fixture the moment you need instead of the real time.

Then run the checks:

```sh
uv run pytest
uv run prek run --all-files
```

## 4. Update the docs

In the same PR:

1. Regenerate the reference: `uv run scripts/gen_reference.py`. It rewrites the command table
   (name, `!` alias, usage, summary) in `docs/reference/_generated/` from `COMMANDS`; commit the
   result. `tests/test_reference_docs.py` fails while the committed files are stale.
2. If the command changes something, add it to the "Behaviour" list of
   [Chat commands](../../reference/chat-commands.md), linking to the page that explains it.
3. If the command changes how the weekly cycle behaves, update the matching
   [explanation page](../../explanation/index.md); if it is a task flatmates will look up, add a
   page to the "In the chat" [how-to guides](../index.md) (`docs/how-to/chat/`, plus `nav` in
   `mkdocs.yml`). How to write either:
   [Write docs](write-docs.md).
4. Build the site: `uv run --group docs zensical build --strict`.

A new command is user-visible, so the PR gets the default minor release (no `release:*` label);
see [Release](release.md).
