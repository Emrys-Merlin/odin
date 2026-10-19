# Move dinner to another day

**How-to guide** — steps for one task you already know you want to do.

Move dinner to another weekday or time from the chat.

Weekdays are written in English (`mon`, `tue`, … or `monday`, …), the time as `HH:MM`. Full
syntax: [Chat commands](../../reference/chat-commands.md). Why ODIN handles the switch like this:
[Changing the dinner weekday](../../explanation/weekday-change.md).

## Only a new time on the same day

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/settime dinner sun 18:30`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Gespeichert ✅<br>
Essen (dinner): So 18:30, nächstes Mal So 25.10. um 18:30<br>
Das gilt schon für diese Woche.<br>
Achtung: Die Ankündigung ist diese Woche schon raus und nennt noch die alte Zeit für dinner (So 18:00). Sag am besten in der Essensgruppe Bescheid, dass jetzt So 18:30 gilt.
</div>
</div>

This applies at once. The last line only appears once the announcement has gone out: then tell
the dinner group yourself.

## Move to another weekday

### 1. Send `/settime dinner <weekday> <HH:MM>`

The running dinner week is never moved. What happens depends on when you send it.

**Before the week has started** (before Tuesday's question), the new day applies at once:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/settime dinner mon 19:00`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Gespeichert ✅<br>
Essen (dinner): So 18:00 → Mo 19:00<br>
Das gilt schon ab dieser Woche: nächstes Essen am Mo 26.10. um 19:00.
</div>
</div>

**After Tuesday's question**, this week's dinner stays and the new day takes over afterwards.
Here a Monday right after the last Sunday would have had its question before the switch, so that
Monday is dropped. ODIN says so, and the dinner group gets a cancellation for it:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/settime dinner mon 19:00`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Gespeichert ✅<br>
Essen (dinner): So 18:00 → Mo 19:00<br>
Das gilt ab dem Essen am Mo 02.11. um 19:00. Diese Woche bleibt es beim Essen am So 25.10. um 18:00.<br>
Achtung: Am Mo 26.10. gibt es kein Essen – diese Woche fällt beim Wechsel aus, weil ihre Frage an die WG schon vor dem Wechsel dran gewesen wäre.<br>
Die Absage für den Mo 26.10. schicke ich der Essensgruppe beim Wechsel (So 25.10. um 18:00).
</div>
</div>

### 2. If ODIN says "Das passt nicht"

All points of the week must stay in order, and cooking comes before dinner. Moving dinner from
Sunday to Saturday while cooking is still on Sunday is refused:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/settime dinner sat 18:00`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Das passt nicht: flat_deadline muss vor cook liegen. Die Zeitpunkte müssen in der Woche bis zum Essen in dieser Reihenfolge liegen: flat_ask → nudge → flat_deadline → tally → dinner; rsvp_by und cook nach flat_deadline (rsvp_by darf gleich sein).
</div>
</div>

Move the other point first (here `/settime cook sat 17:00`), then dinner. Do this before Tuesday's
question if you can: moved later, the cooking time changes for the current week too.

### 3. Check with `/schedule`

A pending change shows on the dinner line, with the first new dinner and a dropped day:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/schedule`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
flat_ask – Frage an die WG: Di 18:00<br>
nudge – Erinnerung: Mi 12:00<br>
flat_deadline – Entscheidung: Mi 18:00<br>
rsvp_by – Rückmeldung bis: Fr 14:00<br>
tally – Zählung: Fr 14:00<br>
cook – Mitkochen: So 17:00<br>
dinner – Essen: So 18:00 → ab 02.11.: Mo 19:00 (Mo 26.10. entfällt) ✏️ 20.10. von Anna

Ändern: /settime &lt;punkt&gt; &lt;tag&gt; &lt;HH:MM&gt; · Zurücksetzen: /resettime &lt;punkt&gt;
</div>
</div>

`/status` shows it too. If one of the texts names a weekday literally ("Sonntag") instead of using
a placeholder, the `/settime` reply ends with a warning to check it; fix it as in
[Edit a text](edit-a-text.md).

## Undo: `/resettime dinner`

While the change is still pending, `/resettime dinner` discards it:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/resettime dinner`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Verworfen ✅ Der geplante Wechsel auf Mo 19:00 (ab Mo 02.11.) fällt weg.<br>
Essen (dinner): So 18:00, nächstes Mal So 25.10. um 18:00
</div>
</div>

A new time on the current weekday (e.g. `/settime dinner sun 18:30`) discards it as well. Once the
new day is in effect, `/resettime dinner` goes back to the config file's day — and that switch
waits for the running week just like `/settime dinner`.
