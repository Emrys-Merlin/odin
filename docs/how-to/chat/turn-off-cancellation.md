# Turn the cancellation off

**How-to guide** — steps for one task you already know you want to do.

Stop ODIN from telling the dinner group "no dinner this week", and turn it back on.

The cancellation is the message the dinner group gets when nobody in the flat confirms dinner.
With it off, guests only hear from ODIN when there is a dinner. Exact syntax:
[Chat commands](../../reference/chat-commands.md). To turn it off for good, set
`cancellation = false` under [`[decision]`](../../reference/configuration.md#decision) in the
config file instead.

## Turn the cancellation off

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/cancellation off`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Gespeichert ✅<br>
Absage an die Essensgruppe (cancellation): aus<br>
Ohne 👍 fällt das Essen weiterhin aus, aber die Essensgruppe bekommt keine Absage – auch nicht per /skip, beim Wechsel des Essenstags oder bei einer Pause ohne eigenen Text. /cancel schickt die Absage trotzdem.<br>
Das gilt schon für diese Woche.
</div>
</div>

It applies to this week as long as Wednesday's decision has not happened yet; after it, the reply
says `Das gilt ab nächster Woche.` instead. Dinner still only takes place if someone reacts 👍 to
the flat ask — nothing changes for the flat group, and the flat ask and the nudge still say that
ODIN will cancel. If you want them to say something else, [edit those texts](edit-a-text.md).

`/schedule` marks the decision:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/schedule`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
flat_ask – Frage an die WG: Di 18:00<br>
nudge – Erinnerung: Mi 12:00<br>
flat_deadline – Entscheidung: Mi 18:00 (ohne Absage an die Essensgruppe) ✏️ 19.10. von Anna<br>
rsvp_by – Rückmeldung bis: Fr 14:00<br>
tally – Zählung: Fr 14:00<br>
cook – Mitkochen: So 17:00<br>
dinner – Essen: So 18:00

Ändern: /settime &lt;punkt&gt; &lt;tag&gt; &lt;HH:MM&gt; · Zurücksetzen: /resettime &lt;punkt&gt;
</div>
</div>

After a week without dinner, `/status` shows that no cancellation went out:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/status`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Sonntag, 25.10.<br>
✅ Frage an die WG gesendet (Di 18:00) – 0× 👍<br>
✅ Erinnerung gesendet (Mi 12:00)<br>
– Absage an die Essensgruppe: nicht gesendet (aus)<br>
– Zählung: entfällt (kein Essen)<br>
Nächste Aktion: Frage an die WG, Di 18:00
</div>
</div>

## Cancel a confirmed dinner anyway

`/cancel` still posts the cancellation, also while it is off: someone decided to tell the guests.
Use it when dinner was announced and then falls through; see
[Cancel a dinner](cancel-dinner.md).

## Turn it back on

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/cancellation on`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Gespeichert ✅<br>
Absage an die Essensgruppe (cancellation): an<br>
Das gilt schon für diese Woche.
</div>
</div>

`/cancellation reset` instead goes back to what the config file says:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/cancellation reset`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Zurückgesetzt ✅ (wieder wie in der Config)<br>
Absage an die Essensgruppe (cancellation): an<br>
Das gilt schon für diese Woche.
</div>
</div>

What exactly the switch covers — skip dates, a new dinner weekday, a break:
[The weekly cycle](../../explanation/weekly-cycle.md#turning-the-cancellation-off).
