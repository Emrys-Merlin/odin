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

Commands are answered in the **flat group**, for everyone in it. In the dinner group, or any
other group, ODIN ignores them.

People on the allowlist `direct_senders` (see [Configuration](configuration.md#commands)) may
also send them to ODIN in a **direct message**; see [Direct messages](#direct-messages). Without
an allowlist, direct messages are ignored.

## Replies outside a command (flat group)

| Message | Reply |
|---|---|
| `/` or `!` plus a letter, but no known command (e.g. `/hilfe`) | `Unbekannter Befehl /hilfe – /help zeigt alle Befehle.` |
| A command that fails unexpectedly | `Da ist etwas schiefgegangen – bitte später nochmal versuchen.` |
| Anything else | None; ODIN ignores it. |

`/help` ends with `Statt / geht auch !, also z. B. !help.`

## Commands

--8<-- "docs/reference/_generated/chat-commands.md"

## Direct messages

A direct message to ODIN is answered only if its sender's number or UUID is on
`direct_senders`. Messages from anyone else, and from ODIN's own number, get no answer and change
nothing; ODIN logs one line at `INFO` with the sender's number and UUID
(`ignoring a direct message from … (UUID …): not in commands.direct_senders`). Steps:
[Allow commands in a direct message](../how-to/operate/allow-direct-commands.md).

From an allowed sender:

| Message | Reply, as a direct message | Flat group |
|---|---|---|
| A command marked *works* above | The same reply as in the flat group | nothing |
| A command marked *works; a change gets the notice*, that changed something | The same reply as in the flat group | The notice, if `direct_notice` is on |
| `/cancel`, `/introduce`, `/hiatus`, and `/skip` with the date of a running week (which is `/cancel`) | `/cancel geht nur in der WG-Gruppe: Dort bestätigt es jemand mit 👍, und alle sehen es.` (with the command line as sent, and the configured emoji) | nothing |
| An unknown command | `Unbekannter Befehl /hilfe – /help zeigt alle Befehle.` | nothing |
| Anything else | `Hier verstehe ich nur Befehle – /help zeigt sie.` | nothing |

The **notice** is one line naming the sender (their profile name, else their number or UUID) and
the first line of the command, cut at 80 characters:

```text
✏️ Tim hat per Direktnachricht geändert: /settime tally fri 15:00
```

It is posted once, after the reply, and only when the command actually stored a change: a
refused change (`/settime` with a time that does not fit) or a command that only shows something
(`/skip` alone lists the skip dates) posts nothing. Commands marked *works* never post it.
With `direct_notice = false`, a direct message posts nothing to the flat group at all.

In a direct message, `/help` ends with an extra line:
`Nur in der WG-Gruppe: /cancel, /introduce, /hiatus.`

## Behaviour

What the commands that change something do in detail is explained elsewhere:

- `/settime`, `/resettime`, `/nudge`: [The weekly cycle](../explanation/weekly-cycle.md); moving
  dinner to another weekday: [Changing the dinner weekday](../explanation/weekday-change.md).
- `/cancel`: [Reactions](../explanation/reactions.md) and
  [The weekly cycle](../explanation/weekly-cycle.md).
- `/introduce`: [Reactions](../explanation/reactions.md) and
  [The weekly cycle](../explanation/weekly-cycle.md#introducing-odin). The text is the
  `introduction` template; see [Templates](templates.md).
- `/skip`, `/unskip`:
  [The weekly cycle](../explanation/weekly-cycle.md#skipping-a-date-in-advance). Skip dates are
  stored in the state DB; there is no config key for them.
- `/hiatus`, `/resume`:
  [The weekly cycle](../explanation/weekly-cycle.md#taking-a-break). The notice is the `hiatus`
  template; see [Templates](templates.md). The hiatus is stored in the state DB; there is no
  config key for it.
- `/settext`, `/resettext`, `/vars`: [Templates](templates.md).
