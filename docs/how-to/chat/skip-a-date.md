# Skip a date in advance

**How-to guide** — steps for one task you already know you want to do.

Enter a Sunday without dinner ahead of time (holidays, everyone away) with `/skip`, list the
entered dates, and take one back with `/unskip`. Syntax and details:
[Chat commands](../../reference/chat-commands.md).

For this week's dinner once the flat has been asked, use [Cancel a dinner](cancel-dinner.md)
instead — `/skip` with this week's date does exactly that.

## 1. Send `/skip` with the date in the flat group

The date is the dinner day, written `YYYY-MM-DD`. ODIN enters it at once and shows the
cancellation the dinner group will get:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/skip 2026-12-27`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Eingetragen: Am Sonntag, 27.12.2026 gibt es kein Essen. Ich frage die WG in der Woche nicht und schicke der Essensgruppe am Mi 23.12. 18:00 diese Absage:

Diesen Sonntag findet leider kein offenes Abendessen statt. Bis zum nächsten Mal!

Unfortunately, there is no open dinner this Sunday. See you next time!

/unskip 2026-12-27 nimmt das zurück.
</div>
</div>

No reaction is needed. In that week the flat group gets no question and no nudge; the dinner
group gets the cancellation at the usual decision time, so guests hear on Wednesday as in any
other week. The text is the cancellation template; to change it, see [Edit a text](edit-a-text.md).

## 2. Check the list

`/skip` without a date lists the upcoming dates and who entered them:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/skip`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Kein Essen an diesen Tagen:<br>
• So 27.12.2026 ✏️ 20.10. von Tim<br>
• So 03.01.2027 ✏️ 20.10. von Tim

Eintragen: /skip JJJJ-MM-TT · Zurücknehmen: /unskip JJJJ-MM-TT
</div>
</div>

`/status` lists them too, and in the skipped week itself shows what happens:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/status`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Sonntag, 27.12.<br>
– Frage an die WG: entfällt (per /skip)<br>
– Erinnerung: entfällt (per /skip)<br>
⏳ Absage an die Essensgruppe: Mi 18:00 – per /skip<br>
– Zählung: entfällt (kein Essen)<br>
Kein Essen per /skip: So 03.01.2027<br>
Nächste Aktion: Absage an die Essensgruppe, Mi 18:00
</div>
</div>

## 3. Take a date back with `/unskip`

Plans changed? `/unskip` with the same date makes it a normal dinner week again:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/unskip 2027-01-03`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Zurückgenommen: Am Sonntag, 03.01.2027 gibt es wieder Essen wie immer.
</div>
</div>

This works until the week's flat question would have gone out (Tuesday 18:00 by default). After
that the week stays cancelled:

<div class="chat" data-group="Flat group" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Zu spät: Die Frage an die WG für das Essen am Sonntag, 27.12.2026 ist schon ausgefallen – das Essen bleibt abgesagt.
</div>
</div>

## If ODIN refuses

- **Not a dinner day:** the date must be a day dinner takes place on (a Sunday by default). After
  a [move to another day](move-dinner-day.md) that is the new weekday from the switch on.
- **In the past**, or **already entered:** nothing to do.
- **This week, already asked:** `/skip` answers like `/cancel` — react 👍 on its reply, see
  [Cancel a dinner](cancel-dinner.md).
- **Dropped by a weekday change:** that week is off anyway and its cancellation goes out on its
  own.

If dinner moves to another weekday after you entered a date, `/skip` marks that date
"(kein Essenstag mehr)": it no longer cancels anything. Enter the new day instead and `/unskip`
the old one.

Why it works this way: [The weekly cycle](../../explanation/weekly-cycle.md#skipping-a-date-in-advance).
