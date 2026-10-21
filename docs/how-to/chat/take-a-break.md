# Take a break

**How-to guide** — steps for one task you already know you want to do.

Put ODIN to sleep with `/hiatus` for a break with no end date (summer, a renovation), and wake
it up again with `/resume`. Syntax and details:
[Chat commands](../../reference/chat-commands.md); how it works:
[Taking a break](../../explanation/weekly-cycle.md#taking-a-break).

For a single Sunday you know in advance, use [Skip a date in advance](skip-a-date.md); for just
this week, [Cancel a dinner](cancel-dinner.md).

## 1. Check the notice text

The dinner group gets one notice when the break starts, the `hiatus` template. Look at it with
`/text hiatus` and change it as in [Edit a text](edit-a-text.md). If `/texts` shows "nicht
gesetzt, es gilt cancellation", there is no notice text yet and the guests would only get the
normal cancellation; set one with `/settext hiatus` first.

## 2. Send `/hiatus` in the flat group

ODIN does not stop yet. It replies with what it will post to the dinner group and asks for a 👍:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/hiatus`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Odin in Pause schicken? Dann reagiert mit 👍 auf diese Nachricht. Bis jemand /resume schreibt, frage ich die WG nicht mehr und schicke der Essensgruppe nichts – außer einmal, was unten steht.<br>
Ohne 👍 passiert nichts; die Anfrage verfällt, wenn das Essen beginnt (So 25.10. 18:00).

Das geht an die Essensgruppe:

Das offene Abendessen macht eine Pause. 💤 Bis auf Weiteres findet kein Abendessen statt – sobald es wieder losgeht, melden wir uns hier wie gewohnt. Bis bald!

The open dinner is taking a break. 💤 Until further notice, there will be no dinner – once it starts again, you will hear from us here as usual. See you soon!
</div>
</div>

If this week's flat ask is already out, this week's dinner is cancelled first, exactly as with
`/cancel`, and the reply says so:

<div class="chat" data-group="Flat group" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Odin in Pause schicken? Dann reagiert mit 👍 auf diese Nachricht. Bis jemand /resume schreibt, frage ich die WG nicht mehr und schicke der Essensgruppe nichts – außer einmal, was unten steht.<br>
Die Frage zum Essen am Sonntag, 25.10. ist schon raus – das sage ich vorher ab, genau wie mit /cancel.<br>
Ohne 👍 passiert nichts; die Anfrage verfällt, wenn das Essen beginnt (So 25.10. 18:00).

Das geht an die Essensgruppe:

Diesen Sonntag findet leider kein offenes Abendessen statt. Bis zum nächsten Mal!

Unfortunately, there is no open dinner this Sunday. See you next time!

Das offene Abendessen macht eine Pause. 💤 Bis auf Weiteres findet kein Abendessen statt – sobald es wieder losgeht, melden wir uns hier wie gewohnt. Bis bald!

The open dinner is taking a break. 💤 Until further notice, there will be no dinner – once it starts again, you will hear from us here as usual. See you soon!
</div>
</div>

## 3. React 👍 on ODIN's reply

Anyone in the flat group can confirm, you too. Within about a minute ODIN posts the notice (after
the cancellation, if there is one) to the dinner group, once:

<div class="chat" data-group="Dinner group" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Das offene Abendessen macht eine Pause. 💤 Bis auf Weiteres findet kein Abendessen statt – sobald es wieder losgeht, melden wir uns hier wie gewohnt. Bis bald!

The open dinner is taking a break. 💤 Until further notice, there will be no dinner – once it starts again, you will hear from us here as usual. See you soon!
</div>
</div>

From now on ODIN asks nothing and posts nothing, week after week. Changed your mind? Remove the 👍
before ODIN's next round, about a minute. If nobody reacts, nothing happens: the request lapses
when this week's dinner starts.

## 4. Check with `/status`

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/status`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Sonntag, 25.10.<br>
😴 Kein Essen – Pause per /hiatus<br>
😴 Pause seit Mo 19.10. 10:01 (von Tim): keine Frage an die WG, nichts an die Essensgruppe.<br>
✅ Hinweis an die Essensgruppe gesendet (Mo 19.10. 10:01)<br>
/resume beendet die Pause.
</div>
</div>

If the hiatus cancelled this week, `/status` shows the week's steps with `❌ Absage gesendet
(Di 19:31) – per /hiatus` above the hiatus lines.

During the break `/skip` still works, for a date after the break; `/cancel` and `/introduce`
are refused:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/cancel`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Ich mache gerade Pause – es gibt nichts abzusagen. /resume beendet die Pause.
</div>
</div>

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/introduce`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Ich mache gerade Pause – /resume beendet sie, danach kann ich mich vorstellen.
</div>
</div>

## 5. Wake ODIN up: `/resume`

Send `/resume` in the flat group. It takes effect at once, needs no 👍 and posts nothing to the
dinner group:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/resume`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Pause beendet ✅ Ab jetzt läuft alles wieder wie gewohnt.<br>
/status zeigt, was als Nächstes kommt.
</div>
</div>

The next flat ask goes out as usual, and the guests hear that dinner is back from the next
announcement (or cancellation). Best send `/resume` before the flat ask day: if this week's flat
ask was already due, the week stays off, and ODIN says so:

<div class="chat" data-group="Flat group" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Pause beendet ✅ Ab jetzt läuft alles wieder wie gewohnt.<br>
Für das Essen am Sonntag, 01.11. war die Frage an die WG schon fällig – das fällt noch aus, ohne Nachricht an die Essensgruppe.<br>
/status zeigt, was als Nächstes kommt.
</div>
</div>

If you still want a dinner that week, tell the dinner group yourself.

## If ODIN refuses

- **Already on a break:** `Ich mache schon Pause, seit Mo 19.10. 10:01 (von Tim). /resume beendet
  die Pause.`
- **Already asked:** a `/hiatus` of this week is waiting for its 👍; react on that earlier reply.
- **Not on a break:** `/resume` answers `Ich mache gerade keine Pause – es läuft alles wie
  gewohnt.`
