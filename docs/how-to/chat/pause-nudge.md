# Pause the nudge

**How-to guide** — steps for one task you already know you want to do.

Turn the Wednesday reminder off or on, and move other schedule points.

The nudge is the reminder ODIN sends to the flat group when nobody has confirmed dinner yet.
Exact syntax: [Chat commands](../../reference/chat-commands.md).

## Turn the nudge off

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/nudge off`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Gespeichert ✅<br>
Erinnerung an die WG (nudge): aus<br>
Das gilt schon für diese Woche.
</div>
</div>

Without the nudge, dinner is still cancelled at the deadline if nobody reacts 👍 — there is just
no warning first. `/schedule` shows the nudge as off:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/schedule`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
flat_ask – Frage an die WG: Di 18:00<br>
nudge – Erinnerung: Mi 12:00 (aus) ✏️ 19.10. von Anna<br>
flat_deadline – Entscheidung: Mi 18:00<br>
rsvp_by – Rückmeldung bis: Fr 14:00<br>
tally – Zählung: Fr 14:00<br>
cook – Mitkochen: So 17:00<br>
dinner – Essen: So 18:00

Ändern: /settime &lt;punkt&gt; &lt;tag&gt; &lt;HH:MM&gt; · Zurücksetzen: /resettime &lt;punkt&gt;
</div>
</div>

## Turn it back on

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/nudge on`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Gespeichert ✅<br>
Erinnerung an die WG (nudge): Mi 12:00, nächstes Mal Mi 21.10. um 12:00<br>
Das gilt schon für diese Woche.
</div>
</div>

`/resettime nudge` instead goes back to what the config file says, for both on/off and the time.

## Move the nudge or another point: `/settime`

`/settime <point> <weekday> <HH:MM>` moves one point of the weekly schedule. The points are
`flat_ask`, `nudge`, `flat_deadline`, `rsvp_by`, `tally`, `cook` and `dinner`; `/schedule` shows
their current times. For example, the tally two hours earlier:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/settime tally fri 12:00`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Gespeichert ✅<br>
Zählung der Gäste (tally): Fr 12:00, nächstes Mal Fr 23.10. um 12:00<br>
Das gilt schon für diese Woche.
</div>
</div>

A change takes effect at once. ODIN refuses it, and saves nothing, when:

- **the order breaks** — the points must stay in their order within the week:

    <div class="chat" data-group="Flat group" markdown>
    <div class="msg me" markdown>
    `/settime tally sun 19:00`
    </div>
    <div class="msg" markdown>
    <span class="sender">Odin 🍽️</span>
    Das passt nicht: flat_deadline muss vor tally liegen. Die Zeitpunkte müssen in der Woche bis zum Essen in dieser Reihenfolge liegen: flat_ask → nudge → flat_deadline → tally → dinner; rsvp_by und cook nach flat_deadline (rsvp_by darf gleich sein).
    </div>
    </div>

- **a step would be due right now** — e.g. on Wednesday at 11:00, moving the nudge to 10:00:

    <div class="chat" data-group="Flat group" markdown>
    <div class="msg me" markdown>
    `/settime nudge wed 10:00`
    </div>
    <div class="msg" markdown>
    <span class="sender">Odin 🍽️</span>
    Dann wäre die Erinnerung sofort fällig – das geht nicht über den Chat.
    </div>
    </div>

- **the current dinner week would move** — only possible through `dinner`; see
  [Move dinner to another day](move-dinner-day.md).

If a message of this week already named the old time, ODIN adds an "Achtung: …" line; tell the
group yourself, for example after moving the deadline once Tuesday's question is out:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/settime flat_deadline thu 12:00`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Gespeichert ✅<br>
Frist für die WG / Entscheidung (flat_deadline): Do 12:00, nächstes Mal Do 22.10. um 12:00<br>
Das gilt schon für diese Woche.<br>
Achtung: Die Frage an die WG ist diese Woche schon raus und nennt noch die alte Frist (Mi 18:00). Sag am besten in der Gruppe Bescheid, dass jetzt Do 12:00 gilt.
</div>
</div>

## Undo: `/resettime <point>`

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/resettime tally`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Zurückgesetzt ✅ (wieder wie in der Config)<br>
Zählung der Gäste (tally): Fr 14:00, nächstes Mal Fr 23.10. um 14:00<br>
Das gilt schon für diese Woche.
</div>
</div>

The same guard applies. Why the schedule works like this: [The weekly cycle](../../explanation/weekly-cycle.md).
