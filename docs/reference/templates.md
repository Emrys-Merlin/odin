# Templates

**Reference** — exact facts to look up.

The weekly message templates and their placeholders. Where the templates are set is in
[Configuration](configuration.md); changing one from the chat is a
[how-to](../how-to/chat/edit-a-text.md).

## Templates

Templates have no defaults: every one must be set in the `[templates]` table of the config file.
The texts of `config.example.toml` are a starting point.

| Template | Sent to | Language | When | Editable via chat |
|---|---|---|---|---|
| `flat_ask` | flat group | German | flat ask: does dinner take place? | yes |
| `nudge` | flat group | German | nudge, only if nobody confirmed yet | yes |
| `announcement` | dinner group | German, blank line, English | decision, if someone confirmed | yes |
| `cancellation` | dinner group | German, blank line, English | decision, if nobody confirmed; also after `/cancel` and for a week dropped by a weekday change | yes |
| `tally` | flat group | German | tally, only if dinner is on | yes |
| `hello` | the operator, direct message | German | `odin setup`, step `hello` | no |
| `flat_test` | flat group | German | end of `odin setup`, optional test | no |

When each step happens is explained in [The weekly cycle](../explanation/weekly-cycle.md). A chat
change (`/settext`) overrides the config file's text until `/resettext`; see
[Chat commands](chat-commands.md).

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
changes. `/vars` lists the same placeholders in the chat, with their current values.

--8<-- "docs/reference/_generated/placeholders.md"
