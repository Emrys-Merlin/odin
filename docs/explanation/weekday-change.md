# Changing the dinner weekday

**Explanation** — background: how ODIN behaves and why.

What happens to the running week when dinner moves to another day.

Moving a time within the week is simple: the [reconcile loop](reliability.md) picks up the new
time on its next tick. Moving *dinner itself* to another weekday is harder, because a dinner week
is defined by its dinner: changing the weekday mid-week would leave a half-run week with no
dinner, or start a new week whose flat ask lies in the past.

## The running week is never touched

When dinner moves to another weekday (`/settime dinner`), the running dinner week keeps its
weekday. Once it has started (flat ask due or anything recorded), the change waits until that
week's dinner; between weeks it applies at once. `/schedule` and `/status` show a pending
change. A new time on the current weekday or `/resettime dinner` discards it.

## Dropped weeks

A week of the new weekday whose steps would all lie before the switch (e.g. Sun → Mon: the
Monday right after the last Sunday dinner) is *dropped*. There is no dinner that week, and
nothing goes to the flat group for it — asking now would be pointless.

But guests may expect a dinner on the new day, so the dinner group gets the normal cancellation,
once, as soon as the switch takes effect (with the new weekday's name). Like any
[late action](reliability.md#catch-up) it is skipped after the dropped week's dinner start, or
once the catch-up grace counted from the switch has passed. The dropped week is stored in the
state DB when the switch is applied, so a restart neither loses nor repeats it. `/cancel` is
refused for a dropped week — it is already cancelled.

## Changes in the config file

The same holds when the dinner weekday is changed **in the config file** and ODIN is restarted.
ODIN stores the dinner the weeks run on. If the config file names another weekday while a dinner
week is running (anything of it already recorded), that week keeps its weekday, and the new one
takes over at its dinner, exactly like a chat change. It is logged as a warning at startup and at
the switch; `/schedule` and `/status` show it, `odin check-config` mentions it. Between weeks it
applies at once. A chat change wins over the config file, as every override does.

## Cleaning up after a switch

After a switch, every week that was started or dropped and is not finished yet is finished (late
steps recorded as skipped), so nothing stays open even if ODIN was down over the switch.

Steps: [Move dinner to another day](../how-to/chat/move-dinner-day.md). Exact syntax:
[Chat commands](../reference/chat-commands.md).
