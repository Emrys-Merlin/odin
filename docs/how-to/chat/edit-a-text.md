# Edit a text

**How-to guide** — steps for one task you already know you want to do.

Look at and change the texts ODIN sends each week.

Six texts can be changed from the flat group: `flat_ask`, `nudge`, `announcement`,
`cancellation`, `weekday_change_cancellation` and `tally`. The example changes Friday's tally.
Exact syntax:
[Chat commands](../../reference/chat-commands.md); all placeholders:
[Templates](../../reference/templates.md).

## 1. Find the text: `/texts`

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/texts`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Texte:<br>
flat_ask (WG-Gruppe) – Frage, ob das Essen stattfindet<br>
nudge (WG-Gruppe) – Erinnerung, wenn noch niemand bestätigt hat<br>
announcement (Essensgruppe) – Ankündigung mit Bitte um Rückmeldung<br>
cancellation (Essensgruppe) – Absage<br>
weekday_change_cancellation (Essensgruppe) – Absage beim Wechsel des Wochentags<br>
tally (WG-Gruppe) – Anzahl der Zusagen zum Bestellen

Anzeigen: /text &lt;name&gt;
</div>
</div>

## 2. Get the current text: `/text <name>`

ODIN answers with two messages: the raw text as a ready-made `/settext` command, and a preview
with this week's values.

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/text tally`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
/settext tally<br>
Bisher haben {count} Personen mit {emoji} auf die Ankündigung reagiert. Plus-Ones stehen gegebenenfalls in den Antworten darauf.
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Vorschau (diese Woche, noch keine Ankündigung – Beispielzahl 3):<br>
Bisher haben 3 Personen mit 👍 auf die Ankündigung reagiert. Plus-Ones stehen gegebenenfalls in den Antworten darauf.
</div>
</div>

The words in braces, like `{count}`, are placeholders that ODIN fills in when it sends the text.

## 3. Check the placeholders: `/vars <name>`

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/vars tally`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Platzhalter für tally:<br>
{emoji} – Reaktion zum Bestätigen: 👍<br>
{flat_ask_day_de} / {flat_ask_day_en} – Frage an die WG (Wochentag): Dienstag / Tuesday<br>
{deadline} – Entscheidung der WG (Uhrzeit): 18:00<br>
{deadline_day_de} / {deadline_day_en} – Entscheidung der WG (Wochentag): Mittwoch / Wednesday<br>
{rsvp_by} – Zusagen bitte bis (Uhrzeit): 14:00<br>
{rsvp_by_day_de} / {rsvp_by_day_en} – Zusagen bitte bis (Wochentag): Freitag / Friday<br>
{cook_time} – Mitkochen (Uhrzeit): 17:00<br>
{cook_day_de} / {cook_day_en} – Mitkochen (Wochentag): Sonntag / Sunday<br>
{dinner_time} – Essen (Uhrzeit): 18:00<br>
{dinner_day_de} / {dinner_day_en} – Essen (Wochentag): Sonntag / Sunday<br>
{count} – Anzahl Zusagen auf die Ankündigung (nur in tally)

{{ und }} schreiben für eine wörtliche Klammer.
</div>
</div>

Use the weekday placeholders instead of writing "Sonntag" yourself, so the text stays right if
dinner moves to another day. Plain `/vars` lists the placeholders of all texts.

## 4. Send the new text: `/settext <name>`

Copy ODIN's `/settext tally` message, edit the text below the first line, and send it. The
command stays alone on the first line; the new text starts on the next one. For the dinner-group
texts (`announcement`, `cancellation`, `weekday_change_cancellation`) keep German first, a
blank line, then English.

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
/settext tally<br>
Schon {count}× {emoji} auf die Einladung – Zeit zum Bestellen! Plus-Ones stehen in den Antworten.
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Gespeichert ✅ So sieht tally jetzt aus:<br>
(Mit der Beispielzahl 3 für {count}.)
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Schon 3× 👍 auf die Einladung – Zeit zum Bestellen! Plus-Ones stehen in den Antworten.
</div>
</div>

The new text applies from the next time ODIN sends it. If this week's message has already gone
out, the reply adds "Für diese Woche ist das schon gelaufen – der Text gilt ab nächster Woche."

A placeholder ODIN does not know is rejected and nothing is saved:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
/settext tally<br>
Schon {anzahl}× {emoji}
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Unbekannter Platzhalter {anzahl}. Welche Platzhalter es gibt, zeigt /vars tally.<br>
(templates.tally: unknown placeholder {anzahl}; allowed: {cook_day_de}, {cook_day_en}, {cook_time}, {count}, {deadline}, {deadline_day_de}, {deadline_day_en}, {dinner_day_de}, {dinner_day_en}, {dinner_time}, {emoji}, {flat_ask_day_de}, {flat_ask_day_en}, {rsvp_by}, {rsvp_by_day_de}, {rsvp_by_day_en})
</div>
</div>

`/texts` now marks the changed text with who changed it when, e.g.
`tally (WG-Gruppe) – Anzahl der Zusagen zum Bestellen ✏️ 19.10. von Anna`.

## Undo: `/resettext <name>`

Back to the text from the config file:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/resettext tally`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Zurückgesetzt auf den Standardtext ✅ So sieht tally jetzt aus:<br>
(Mit der Beispielzahl 3 für {count}.)
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Bisher haben 3 Personen mit 👍 auf die Ankündigung reagiert. Plus-Ones stehen gegebenenfalls in den Antworten darauf.
</div>
</div>

If the text was not changed, ODIN says `tally war nicht geändert.`
