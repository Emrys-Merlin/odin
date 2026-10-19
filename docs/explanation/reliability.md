# Reliability

**Explanation** — background: how ODIN behaves and why.

How ODIN never posts twice and catches up after downtime.

ODIN runs on a small home server that gets restarted, upgraded and occasionally goes down. The
weekly cycle must survive all of that without guests getting two announcements — or none.

## A reconcile loop, not a timer

The scheduler is a *reconcile loop*: on every tick it computes what should have happened by now
from config + state, and does what is missing. It never "sleeps until Tuesday".

A timer would lose its place on every restart and would need to be rebuilt from scratch whenever
someone moves a time from the chat. The reconcile loop has no such state to lose: restarts and
missed ticks are therefore safe, and a changed schedule simply takes effect on the next tick.

## Nothing is ever posted twice

State lives in SQLite. Every action is recorded once sent; **nothing is ever posted twice**.

The one exception: a send that times out while waiting for Signal's answer is retried, though it
may have gone out. For that case ODIN chooses *at least once* over *at most once* — a missing
cancellation is worse than a duplicate. A send that Signal accepted is recorded even if its
answer can't be read.

## Unreadable send responses

To count reactions, ODIN must know which message they belong to, and it learns that from
Signal's answer to the send. If that answer is unreadable for the flat poll or the announcement,
ODIN cannot tell which message the 👍 belong to. It then tells the flat group once (a German
notice, not a template — it explains a fault of ODIN, so it must work whatever the templates
say):

- **Flat poll:** it asks again, and the 👍 on that new message count instead.
- **Announcement:** it warns that the tally will show 0, so the 👍 must be counted by hand.

<div class="chat" data-group="Flat group" markdown>
<div class="msg" markdown>
<span class="sender">Odin 🍽️</span>
⚠️ Meine Frage zum Essen am Sonntag ist rausgegangen, aber ich kann die 👍 darauf nicht
zählen (Signal hat mir nicht gesagt, welche Nachricht es war).
Bitte reagiert stattdessen auf diese Nachricht mit 👍, wenn das Essen stattfindet – bis
Mittwoch 18:00. Ohne 👍 hier sage ich das Essen ab.
</div>
</div>

`/status` shows such a message as "nicht zählbar". Once a week is
[cancelled via `/cancel`](weekly-cycle.md#cancelling-from-the-chat) no reactions are needed any
more, so neither notice is sent for it.

## Catch-up

An action that is late (bot was down) is still performed while within a grace window — by
default until dinner starts — and skipped after that. A flat ask on Thursday is still useful; an
announcement after dinner has started is not. The window is `catch_up_grace` in the
[configuration](../reference/configuration.md). Skipped actions are recorded as skipped, so
`/status` can show them and they are not tried again.
