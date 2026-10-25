# Templates

**Reference** — exact facts to look up.

The weekly message templates and their placeholders. Where the templates are set is in
[Configuration](configuration.md); changing one from the chat is a
[how-to](../how-to/chat/edit-a-text.md).

## Templates

Templates have no defaults: every one must be set in the `[templates]` table of the config file,
except three optional ones: `weekday_change_cancellation`, which falls back to `cancellation`
while it is not set, `introduction`, without which `/introduce` asks for a text instead of sending
anything, and `hiatus`, which falls back to `cancellation`. The texts of `config.example.toml` are a starting point.

| Template | Sent to | Language | When | Editable via chat |
|---|---|---|---|---|
| `flat_ask` | flat group | German | flat ask: does dinner take place? | yes |
| `nudge` | flat group | German | nudge, only if nobody confirmed yet | yes |
| `announcement` | dinner group | German, blank line, English | decision, if someone confirmed | yes |
| `cancellation` | dinner group | German, blank line, English | decision, if nobody confirmed, unless switched off (`decision.cancellation`, `/cancellation off`); also after `/cancel` | yes |
| `weekday_change_cancellation` | dinner group | German, blank line, English | when a new dinner weekday takes over and drops a week (see [Changing the dinner weekday](../explanation/weekday-change.md#dropped-weeks)); optional, falls back to `cancellation` | yes |
| `tally` | flat group | German | tally, only if dinner is on | yes |
| `introduction` | dinner group | German, blank line, English | after a confirmed `/introduce`, any number of times; not part of the weekly cycle; optional, no fallback | yes |
| `hiatus` | dinner group | German, blank line, English | once, when a confirmed `/hiatus` takes effect, after the running week's cancellation if the hiatus cancels it (see [Taking a break](../explanation/weekly-cycle.md#taking-a-break)); not part of the weekly cycle; optional, falls back to `cancellation`, which is then left out if the dinner group already has the running week's cancellation | yes |
| `hello` | the operator, direct message | German | `odin setup`, step `hello` | no |
| `flat_test` | flat group | German | end of `odin setup`, optional test | no |

When each step happens is explained in [The weekly cycle](../explanation/weekly-cycle.md). A chat
change (`/settext`) overrides the config file's text until `/resettext`; see
[Chat commands](chat-commands.md). While `weekday_change_cancellation` is not set (neither in the
config file nor via chat), `/texts` and `/text` mark it with "nicht gesetzt, es gilt
cancellation", and a change of `cancellation` changes it too. While `introduction` is not set,
`/texts` marks it with "nicht gesetzt", and `/text introduction` and `/introduce` answer
`introduction ist nicht gesetzt. Anlegen: /settext introduction – und in den Zeilen darunter der
Text.`; `/resettext introduction` of a text set only via chat answers `Zurückgesetzt ✅
introduction ist jetzt nicht gesetzt.` While `hiatus` is not set, `/texts` and `/text` mark it
with "nicht gesetzt, es gilt cancellation", and the reply to `/hiatus` adds `Es gibt noch keinen
eigenen Text für die Pause; /settext hiatus legt einen an.`

## Syntax

- `{name}` is replaced by the placeholder's value. Only the placeholders allowed in the template
  (table below) may be used; an unknown one is an error — at startup for the config file, as a
  German reply for `/settext`.
- `{{` and `}}` write a literal `{` and `}`.
- A placeholder takes no format spec or conversion: `{deadline:>5}` and `{emoji!r}` are errors.
- Leading and trailing whitespace of a template is stripped.

## Placeholders

Weekdays have a German (`_de`) and an English (`_en`) variant; times are `HH:MM`. Using the
placeholders instead of writing weekday names and times keeps the texts right when the schedule
changes. Dates are `DD.MM.` (`26.10.`). `/vars` lists the same placeholders in the chat, with
their current values.

--8<-- "docs/reference/_generated/placeholders.md"
