# Reactions

**Explanation** — background: how ODIN behaves and why.

Which 👍 count, which don't, and why.

ODIN asks for reactions instead of replies: a reaction is one tap, needs no wording, and can be
counted without parsing text. The emoji is 👍 by default and configurable (`emoji` in the
[configuration](../reference/configuration.md)); "👍" below means whatever is configured.

## The rules

- A 👍 from **anyone** in the flat group counts. No member list.
- Removing a reaction before the deadline withdraws it (this covers "reacted by mistake").
- Reactions after the deadline, and other emojis, are ignored.
- The tally counts the configured emoji on the dinner announcement at tally time.
- A `/cancel` request is confirmed by the configured emoji on ODIN's reply, from anyone in the
  flat group, until the week's dinner starts; removing it before ODIN's next tick withdraws it.
- A reaction counts only in the group its message went to, even after the groups are changed.

## Why

**Anyone in the flat group counts.** Membership of the flat group already says who lives in the
flat. A separate member list in ODIN would have to be kept in sync by hand each time someone
moves in or out — and would get it wrong exactly when it matters.

**Tied to the group of the message.** ODIN remembers, for every message whose reactions it counts,
the group it sent it to. A reaction that claims to be on that message from any other group is
ignored, so a guest can never vote in the flat poll. The same record keeps a week running when
the groups are changed mid-week: the flat ask in the old flat group still collects its 👍, as
long as ODIN is still in that group (see [Change the groups](../how-to/operate/change-groups.md)).

**Withdrawal before the deadline.** People tap the wrong message or change their plans. Taking
the 👍 back is the natural way to undo it, so ODIN honours it, as long as the decision has not
been made yet.

**Nothing after the deadline.** At the flat deadline ODIN has already told the dinner group;
a later 👍 cannot undo an announcement or a cancellation that went out. Ignoring it keeps the
state ODIN acted on and the state it reports the same. Other emojis are ignored so that ❤️ or 😂
can be used freely without voting.

**The tally is a snapshot.** It counts the 👍 on the announcement at tally time, because that is
when food gets ordered. Guests may still react afterwards; the announcement asks for reactions
"ideally by" the RSVP time, not strictly. Plus-ones are written as replies and counted by humans.

**Confirming `/cancel`.** Cancelling is the one action a single flatmate can trigger that the
whole dinner group sees and that cannot be taken back. A confirming reaction on ODIN's reply —
which shows the exact text that would go out — guards against typos and second thoughts. As with
the flat poll, anyone in the flat group may confirm, the requester included. Removing the
reaction before ODIN's next tick withdraws it; once ODIN has acted, the cancellation is out. See
[The weekly cycle](weekly-cycle.md#cancelling-from-the-chat) for how it fits into the week.

If ODIN cannot tell which message a 👍 belongs to, it cannot count it at all; how it handles that
is described in [Reliability](reliability.md#unreadable-send-responses).
