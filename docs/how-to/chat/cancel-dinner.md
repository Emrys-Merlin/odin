# Cancel a dinner

**How-to guide** — steps for one task you already know you want to do.

Cancel this week's dinner from the flat group with `/cancel`.

This works before and after the announcement went out. "This week" is the dinner that has not
started yet. Syntax and details: [Chat commands](../../reference/chat-commands.md).

## 1. Send `/cancel` in the flat group

ODIN does not cancel yet. It replies with the cancellation it would post and asks for a 👍:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/cancel`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Das Essen am Sonntag, 25.10. absagen? Dann reagiert mit 👍 auf diese Nachricht – ich schicke der Essensgruppe dann diese Absage:<br>
Die Einladung ist schon raus (2× 👍); die Absage kommt dann hinterher.<br>
Ohne 👍 passiert nichts; die Anfrage verfällt, wenn das Essen beginnt (So 25.10. 18:00).

Diesen Sonntag findet leider kein offenes Abendessen statt. Bis zum nächsten Mal!

Unfortunately, there is no open dinner this Sunday. See you next time!
</div>
</div>

The line "Die Einladung ist schon raus …" only appears once the announcement was posted; it shows
how many guests have already reacted, so you know whom the cancellation reaches.

## 2. React 👍 on ODIN's reply

Anyone in the flat group can confirm, you too. Within about a minute ODIN posts the cancellation
to the dinner group:

<div class="chat" data-group="Dinner group" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Diesen Sonntag findet leider kein offenes Abendessen statt. Bis zum nächsten Mal!

Unfortunately, there is no open dinner this Sunday. See you next time!
</div>
</div>

The text is the cancellation template; to change it, see [Edit a text](edit-a-text.md). The
dinner group gets it once, even if more people react.

Changed your mind? Remove the 👍 quickly — before ODIN's next round, about a minute. Once the
cancellation is out, it cannot be taken back from the chat; write to the dinner group yourself.

If nobody reacts, nothing happens: the request lapses when the dinner starts.

## 3. Check with `/status`

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/status`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Sonntag, 25.10.<br>
✅ Frage an die WG gesendet (Di 18:00) – 1× 👍<br>
✅ Erinnerung gesendet (Mi 12:00)<br>
✅ Einladung gesendet (Mi 18:00) – 2× 👍<br>
❌ Absage gesendet (Fr 19:10) – per /cancel<br>
⏭️ Zählung: übersprungen (kein Essen)<br>
Nächste Aktion: Frage an die WG, Di 18:00
</div>
</div>

Friday's tally is skipped. Cancelled before Wednesday's deadline, the cancellation replaces
Wednesday's decision and the nudge is skipped, so the dinner group never sees an announcement.

## If ODIN refuses

- **Already asked:** a `/cancel` of this week is waiting for its 👍. React on that earlier reply
  instead of sending a new one:

    <div class="chat" data-group="Flat group" markdown>
    <div class="msg" markdown>
    <span class="sender">Odin 🍽️</span>
    Die Absage für das Essen am Sonntag, 25.10. ist schon angefragt (Fr 23.10. 19:00) – reagiert mit 👍 auf meine Nachricht von da.
    </div>
    </div>

- **Already cancelled:** nothing left to do.

    <div class="chat" data-group="Flat group" markdown>
    <div class="msg" markdown>
    <span class="sender">Odin 🍽️</span>
    Das Essen am Sonntag, 25.10. ist schon abgesagt (Absage gesendet Fr 23.10. 19:10).
    </div>
    </div>

- **Cancellation skipped:** ODIN was down too long and skipped the cancellation; it will not send
  one now. Tell the dinner group yourself.
- **Dropped by a weekday change:** that week is off anyway and its cancellation goes out on its
  own; see [Move dinner to another day](move-dinner-day.md).

Why it needs a reaction and when exactly it is sent: [Reactions](../../explanation/reactions.md)
and [The weekly cycle](../../explanation/weekly-cycle.md).
