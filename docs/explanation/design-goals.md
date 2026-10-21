# Design goals

**Explanation** — background: how ODIN behaves and why.

What ODIN is for, and what it deliberately does not do.

ODIN — *Open Dinner Invitation Notifier* — is a Signal bot that organises the weekly open Sunday
dinner at our flat share. The repo is `odin` (called `odib` until v0.3.0); the bot's Signal
display name is **Odin 🍽️**.

## Goals

ODIN answers two questions every week (see [The weekly cycle](weekly-cycle.md)):

1. **Does dinner take place?** If nobody from the flat is home, guests are told it is cancelled.
2. **How much food do we need?** If dinner happens, the flat gets a rough head count by Friday
   afternoon to order food.

From that follow a few principles:

- **Little effort for people.** Flatmates confirm and guests RSVP with one reaction; nobody has
  to remember to ask. See [Reactions](reactions.md).
- **Silence is a decision.** Without a confirmation, dinner is cancelled — guests are never left
  guessing.
- **Never twice, never forgotten.** Restarts and downtime must not lead to duplicate or missing
  messages. See [Reliability](reliability.md).
- **Configurable without a release.** Times and texts live in the config and can be changed from
  the chat. See [Configuration](../reference/configuration.md) and
  [Chat commands](../reference/chat-commands.md).
- **Simple to run.** One small VM, two containers, no API tokens. See
  [Architecture](architecture.md).

## Language

- Dinner group: **bilingual**, German first, then English, in one message — guests include
  people who don't speak German.
- Flat group: German.
- The messages of the weekly cycle are templates in the config (placeholders like `{deadline}`,
  `{cook_time}`; see [Templates](../reference/templates.md)), so their wording can change
  without a release.
- Chat-command replies are German UI strings in code, not config templates: they explain ODIN
  itself and must stay correct whatever the templates say.
- Command names and their arguments are English only (`/nudge on`, weekdays as `thu`), never
  mixed with German; replies are in German. Commands are answered in the flat group, so
  guests never see the bot's controls. People on an allowlist may also send them in a direct
  message, to spare the flat group the round trip; a change made that way is told to the flat
  group in one line, unless the flat turns that off. Anyone else writing to ODIN directly gets
  no answer. See [Chat commands](../reference/chat-commands.md).

## Non-goals for the MVP

Tracked as separate issues where useful:

- Taking a `/cancel` back once it went out.
- Counting plus-ones automatically ([#13](https://github.com/Emrys-Merlin/odin/issues/13)); guest
  names or lists.
- More than one dinner per week; reminders to guests.
