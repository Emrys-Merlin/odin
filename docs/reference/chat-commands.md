# Chat commands

**Reference** — exact facts to look up.

Every chat command, its arguments and its effect. Step-by-step guides are in the
[chat how-tos](../how-to/index.md); what the weekly steps are is explained in
[The weekly cycle](../explanation/weekly-cycle.md).

## Syntax

- A command is a message that starts with `/` or `!` followed by the command name: `/help` and
  `!help` are the same. Leading whitespace is ignored.
- The command name is case-insensitive (`/Help`, `!HELP`). It runs up to the first whitespace and
  consists of letters only; `/help2` is an unknown command, not `/help`.
- Everything after the name is the argument text. `/settext <name>` takes the new text from the
  lines below the command.
- Command names and arguments are English (`/nudge on`, weekdays as `thu` or `thursday`, as in the
  [configuration](configuration.md)). Replies are German.

## Where commands work

Commands are answered in the **flat group only**. In the dinner group, or any other group, ODIN
ignores them.

## Replies outside a command

| Message | Reply |
|---|---|
| `/` or `!` plus a letter, but no known command (e.g. `/hilfe`) | `Unbekannter Befehl /hilfe – /help zeigt alle Befehle.` |
| A command that fails unexpectedly | `Da ist etwas schiefgegangen – bitte später nochmal versuchen.` |
| Anything else | None; ODIN ignores it. |

`/help` ends with `Statt / geht auch !, also z. B. !help.`

## Commands

--8<-- "docs/reference/_generated/chat-commands.md"

## Behaviour

What the commands that change something do in detail is explained elsewhere:

- `/settime`, `/resettime`, `/nudge`: [The weekly cycle](../explanation/weekly-cycle.md); moving
  dinner to another weekday: [Changing the dinner weekday](../explanation/weekday-change.md).
- `/cancel`: [Reactions](../explanation/reactions.md) and
  [The weekly cycle](../explanation/weekly-cycle.md).
- `/skip`, `/unskip`:
  [The weekly cycle](../explanation/weekly-cycle.md#skipping-a-date-in-advance). Skip dates are
  stored in the state DB; there is no config key for them.
- `/settext`, `/resettext`, `/vars`: [Templates](templates.md).
