# Introduce ODIN to the dinner group

**How-to guide** — steps for one task you already know you want to do.

Post ODIN's self-introduction to the dinner group with `/introduce`, e.g. when ODIN has just
joined it or new people did.

You can do this as often as you like; it changes nothing in the weekly cycle. Syntax:
[Chat commands](../../reference/chat-commands.md); the text is the `introduction` template, see
[Templates](../../reference/templates.md).

## Before you start

ODIN needs an introduction text. If `/introduce` answers `introduction ist nicht gesetzt.`, there
is none yet. Either whoever runs ODIN adds `introduction` from `config.example.toml` to the
config file (see [Configuration](../../reference/configuration.md#templates)), or you write one
yourself with `/settext introduction` (see [Edit a text](edit-a-text.md)).

ODIN must not be on a break. During a [hiatus](take-a-break.md) the introduction, which describes
the weekly messages, would be wrong, so `/introduce` is refused until someone sends `/resume`:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/introduce`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Ich mache gerade Pause – /resume beendet sie, danach kann ich mich vorstellen.
</div>
</div>

## 1. Send `/introduce` in the flat group

ODIN does not post yet. It replies with the introduction it would post and asks for a 👍:

<div class="chat" data-group="Flat group" markdown>
<div class="msg me" markdown>
`/introduce`
</div>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Soll ich mich der Essensgruppe vorstellen? Dann reagiert mit 👍 auf diese Nachricht – ich schicke der Essensgruppe dann diesen Text:<br>
Ohne 👍 passiert nichts; die Anfrage verfällt am Do 22.10. 19:00 oder mit dem nächsten /introduce.

Hallo, ich bin Odin 🍽️, der Bot für das offene Abendessen am Sonntag!<br>
Jeden Mittwoch um 18:00 schreibe ich hier, ob am Sonntag das Essen stattfindet – oder ob es diesmal ausfällt.<br>
Wenn du kommst, reagiere bitte mit 👍 auf meine Ankündigung, am besten bis Freitag 14:00 – dann bestellen wir das Essen. Bringst du jemanden mit? Dann schreib das bitte als Antwort auf die Ankündigung.<br>
Essen gibt es um 18:00. Wer mag, kann schon um 17:00 kommen und beim Kochen helfen – das ist völlig freiwillig. Fragen beantworten die Leute aus der WG gern.

Hi, I'm Odin 🍽️, the bot for the open Sunday dinner!<br>
Every Wednesday at 18:00 I post here whether dinner takes place on Sunday – or whether it is cancelled this time.<br>
If you are coming, please react with 👍 to my announcement, ideally by Friday 14:00 – that is when we order the food. Bringing someone? Please say so in a reply to the announcement.<br>
Dinner is at 18:00. If you like, come at 17:00 and help cook – that is entirely optional. The people from the flat are happy to answer any questions.
</div>
</div>

If ODIN has introduced itself before, the reply also says when, e.g. `Zuletzt vorgestellt: Mi
14.10. 19:05.`

Want different wording? Change the text with `/settext introduction` (see
[Edit a text](edit-a-text.md)), then send `/introduce` again: the new request replaces the old
one, and a 👍 on the old preview does nothing.

## 2. React 👍 on ODIN's reply

Anyone in the flat group can confirm, you too. Within about a minute ODIN posts the introduction
to the dinner group — the text below the blank line of its reply:

<div class="chat" data-group="Dinner group" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
Hallo, ich bin Odin 🍽️, der Bot für das offene Abendessen am Sonntag!<br>
Jeden Mittwoch um 18:00 schreibe ich hier, ob am Sonntag das Essen stattfindet – oder ob es diesmal ausfällt.<br>
Wenn du kommst, reagiere bitte mit 👍 auf meine Ankündigung, am besten bis Freitag 14:00 – dann bestellen wir das Essen. Bringst du jemanden mit? Dann schreib das bitte als Antwort auf die Ankündigung.<br>
Essen gibt es um 18:00. Wer mag, kann schon um 17:00 kommen und beim Kochen helfen – das ist völlig freiwillig. Fragen beantworten die Leute aus der WG gern.

Hi, I'm Odin 🍽️, the bot for the open Sunday dinner!<br>
Every Wednesday at 18:00 I post here whether dinner takes place on Sunday – or whether it is cancelled this time.<br>
If you are coming, please react with 👍 to my announcement, ideally by Friday 14:00 – that is when we order the food. Bringing someone? Please say so in a reply to the announcement.<br>
Dinner is at 18:00. If you like, come at 17:00 and help cook – that is entirely optional. The people from the flat are happy to answer any questions.
</div>
</div>

The dinner group gets it once per request, even if more people react. To post it again later,
send a new `/introduce` and confirm that one.

Changed your mind? Remove the 👍 quickly — before ODIN's next round, about a minute. If nobody
reacts, nothing happens: the request lapses after 24 hours. If a hiatus starts before ODIN
posted the introduction, it is dropped and not posted after `/resume` either; send a new
`/introduce` then.

Why it needs a reaction: [Reactions](../../explanation/reactions.md). How it relates to the week:
[The weekly cycle](../../explanation/weekly-cycle.md#introducing-odin).
