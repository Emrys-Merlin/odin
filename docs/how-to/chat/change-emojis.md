# Change the emojis

**How-to guide** — steps for one task you already know you want to do.

Use other reactions for "I'm coming" and "I'm coming and I'll help cook".

ODIN counts two reactions. **attend** (👍 by default) confirms the flat ask and requests like
`/cancel`, and on the announcement it means "I'm coming". **cook** (🍳 by default) means "I'm
coming and I'll help cook" and counts only on the announcement. Why there are two and how they
are counted: [Reactions](../../explanation/reactions.md). Exact syntax:
[Chat commands](../../reference/chat-commands.md). To change them for good, set `emoji` and
`cook_emoji` in the [config file](../../reference/configuration.md#top-level) instead.

## See the current emojis

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/emoji`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Reaktionen:<br>
attend: 👍 – „ich komme“ auf der Einladung; bestätigt auch die Frage an die WG und Anfragen wie /cancel<br>
cook: 🍳 – „ich komme und helfe beim Kochen“ auf der Einladung (zählt auch als Zusage)
</div>
</div>

## Change one

Send `/emoji cook` or `/emoji attend` with exactly one emoji:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/emoji cook 🧑‍🍳`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Gespeichert ✅<br>
Reaktionen:<br>
attend: 👍 – „ich komme“ auf der Einladung; bestätigt auch die Frage an die WG und Anfragen wie /cancel<br>
cook: 🧑‍🍳 – „ich komme und helfe beim Kochen“ auf der Einladung (zählt auch als Zusage) ✏️ 19.10. von Anna<br>
Das gilt ab meiner nächsten Nachricht. Was schon rausgegangen ist, zählt weiter die Reaktionen, nach denen es gefragt hat.
</div>
</div>

The change applies from ODIN's next message on. A message that has gone out already keeps
counting the emojis it asked for: if this week's announcement said 🍳, the 🍳 on it still count,
and the tally reports them. Texts that use the placeholders `{emoji}` and `{cook_emoji}` show the
new emoji by themselves. If a text has the emoji written out, [edit that text](edit-a-text.md).

The two emojis must differ; a skin tone does not make them different:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/emoji cook 👍🏽`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
👍🏽 ist schon die andere Reaktion (attend: 👍) – die beiden müssen sich unterscheiden, sonst kann ich Kommen und Mitkochen nicht auseinanderhalten.
</div>
</div>

## Undo

`/emoji reset cook` or `/emoji reset attend` goes back to the config file for one of them,
`/emoji reset` for both:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/emoji reset`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Zurückgesetzt ✅ (wieder wie in der Config)<br>
Reaktionen:<br>
attend: 👍 – „ich komme“ auf der Einladung; bestätigt auch die Frage an die WG und Anfragen wie /cancel<br>
cook: 🍳 – „ich komme und helfe beim Kochen“ auf der Einladung (zählt auch als Zusage)<br>
Das gilt ab meiner nächsten Nachricht. Was schon rausgegangen ist, zählt weiter die Reaktionen, nach denen es gefragt hat.
</div>
</div>

If nothing was changed, ODIN says `Die Reaktionen waren nicht geändert – sie sind wie in der
Config.`
