# Your first week with ODIN

**Tutorial** — a guided lesson: follow along and learn by doing.

For flatmates: one dinner week from the flat group's view, and what to tap when.

ODIN (shown in Signal as **Odin 🍽️**) sits in two groups: the **flat group** with just us
flatmates, and the **dinner group** with everyone who is invited. All you ever do is react with
👍 and, if you like, type a command. We follow one week, with dinner on Sunday 25 October, and
the default schedule. Your flat may have moved some times; `/schedule` shows yours.

## Tuesday 18:00 — ODIN asks the flat

ODIN asks in the flat group whether dinner takes place this Sunday:

<div class="chat" data-group="Flat group" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Findet am Sonntag das offene Abendessen statt? 🍽️<br>
Wer da ist und das Abendessen ausrichtet, reagiert bitte bis Mittwoch 18:00 mit 👍 auf diese Nachricht. Ein 👍 reicht – ohne 👍 sage ich das Abendessen am Mittwoch um 18:00 ab.
</div>
</div>

If you are home on Sunday and will host, long-press the message and react with 👍. One 👍 from
anyone in the flat group is enough. Reacted by mistake? Remove the reaction before Wednesday
18:00 and it no longer counts. A plain "ja" in the chat does not count — only the reaction does.

## Wednesday 12:00 — the nudge

This week nobody has reacted by Wednesday noon, so ODIN reminds the flat group:

<div class="chat" data-group="Flat group" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Bisher hat noch niemand mit 👍 bestätigt, dass das Abendessen am Sonntag stattfindet. Wenn bis Mittwoch 18:00 kein 👍 auf meine Frage kommt, sage ich es ab.
</div>
</div>

Ben scrolls up and reacts 👍 on Tuesday's question — not on the nudge. Had someone reacted
earlier, ODIN would have stayed quiet.

<div class="chat" data-group="Flat group" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Findet am Sonntag das offene Abendessen statt? 🍽️<br>
Wer da ist und das Abendessen ausrichtet, reagiert bitte bis Mittwoch 18:00 mit 👍 auf diese Nachricht. Ein 👍 reicht – ohne 👍 sage ich das Abendessen am Mittwoch um 18:00 ab.
<span class="reactions">👍 1</span>
</div>
</div>

## Wednesday 18:00 — the dinner group hears about it

At the deadline ODIN posts to the dinner group. Because there is a 👍, it is the announcement, in
German and English:

<div class="chat" data-group="Dinner group" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Diesen Sonntag gibt es offenes Abendessen! 🍽️<br>
Essen gibt es um 18:00. Wer mag, kann schon um 17:00 kommen und beim Kochen helfen – das ist völlig freiwillig und überhaupt keine Voraussetzung.<br>
Wenn du kommst, reagiere bitte mit 👍 auf diese Nachricht, am besten bis Freitag 14:00 – dann bestellen wir das Essen. Bringst du jemanden mit? Dann schreib das bitte als Antwort auf diese Nachricht.

Open dinner this Sunday! 🍽️<br>
Dinner is at 18:00. If you like, come at 17:00 and help cook – that is entirely optional and absolutely no requirement.<br>
If you are coming, please react with 👍 to this message, ideally by Friday 14:00 – that is when we order the food. Bringing someone? Please say so in a reply to this message.
<span class="reactions">👍 3</span>
</div>
</div>

Guests react with 👍 if they come, and mention plus-ones in a reply.

Without any 👍 on Tuesday's question, the dinner group would instead have got the cancellation:

<div class="chat" data-group="Dinner group" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Diesen Sonntag findet leider kein offenes Abendessen statt. Bis zum nächsten Mal!

Unfortunately, there is no open dinner this Sunday. See you next time!
</div>
</div>

## Friday 14:00 — the tally

Time to order food. ODIN tells the flat group how many 👍 the announcement has:

<div class="chat" data-group="Flat group" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Bisher haben 3 Personen mit 👍 auf die Ankündigung reagiert. Plus-Ones stehen gegebenenfalls in den Antworten darauf.
</div>
</div>

ODIN only counts reactions. Plus-ones are in the replies to the announcement — look there and
add them yourself. After Sunday's dinner the next week starts with Tuesday's question again.

## Try a command: `/help`

Commands work in the flat group only. Type `/help`:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/help`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Das kann ich:<br>
/help – Zeigt alle Befehle.<br>
/status – Zeigt den Stand dieser Woche und die nächste Aktion.<br>
/schedule – Zeigt den Wochenplan.<br>
/texts – Listet die änderbaren Texte.<br>
/text &lt;name&gt; – Zeigt einen Text zum Kopieren und als Vorschau.<br>
/settext &lt;name&gt; – Ändert einen Text; der neue Text kommt in die Zeilen darunter.<br>
/resettext &lt;name&gt; – Setzt einen Text auf den Standardtext zurück.<br>
/vars [name] – Zeigt die Platzhalter für Texte mit ihren aktuellen Werten.<br>
/settime &lt;punkt&gt; &lt;tag&gt; &lt;HH:MM&gt; – Verschiebt einen Zeitpunkt im Wochenplan.<br>
/resettime &lt;punkt&gt; – Setzt einen Zeitpunkt auf den Wert aus der Config zurück.<br>
/nudge on|off – Schaltet die Erinnerung an die WG an oder aus.<br>
/cancel – Sagt das Essen dieser Woche ab – nach Bestätigung per Reaktion.<br>
/skip [JJJJ-MM-TT] – Trägt einen Tag ohne Essen im Voraus ein; ohne Datum: zeigt die Liste.<br>
/unskip &lt;JJJJ-MM-TT&gt; – Nimmt einen mit /skip eingetragenen Tag zurück.<br>
/version – Zeigt, welche Version von Odin läuft.

Statt / geht auch !, also z. B. !help.
</div>
</div>

`!help` works just as well. A typo gets a short hint instead:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/hilfe`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Unbekannter Befehl /hilfe – /help zeigt alle Befehle.
</div>
</div>

Command names and their arguments are English; ODIN answers in German.

## Ask where the week stands: `/status`

`/status` shows each step of this week and what comes next. Sent on Thursday of our week:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/status`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Sonntag, 25.10.<br>
✅ Frage an die WG gesendet (Di 18:00) – 1× 👍<br>
✅ Erinnerung gesendet (Mi 12:00)<br>
✅ Einladung gesendet (Mi 18:00) – 3× 👍<br>
⏳ Zählung: Fr 14:00<br>
Nächste Aktion: Zählung, Fr 14:00
</div>
</div>

✅ is done, ⏳ is still to come. The counts are the 👍 on the flat question and on the
announcement right now.

## What you learned

- React 👍 on Tuesday's question if you host; one is enough.
- Wednesday evening the dinner group gets the announcement or the cancellation.
- Friday's tally tells you how much food to order; add the plus-ones from the replies.
- `/help` lists the commands, `/status` shows the week.

## Next steps

- [Cancel a dinner](../how-to/chat/cancel-dinner.md) after it was announced.
- [Skip a date in advance](../how-to/chat/skip-a-date.md) when you already know there is no
  dinner.
- [Edit a text](../how-to/chat/edit-a-text.md) ODIN sends.
- [Move dinner to another day](../how-to/chat/move-dinner-day.md).
- [Pause the nudge](../how-to/chat/pause-nudge.md) or move other times.
- Every command in detail: [Chat commands](../reference/chat-commands.md). Why the week runs
  like this: [The weekly cycle](../explanation/weekly-cycle.md) and
  [Reactions](../explanation/reactions.md).
