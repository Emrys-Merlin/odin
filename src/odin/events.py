"""The bot's single consumer of incoming Signal events: reactions and chat commands.

Signal fans every event out to each WebSocket client, so the bot opens one event stream and
dispatches from it:

- a `ReactionEvent` is applied to the store (`odin.reactions.handle_reaction`);
- a `GroupMessage` in the flat group is handed to the chat commands (`odin.commands.handle`)
  and each reply is sent back to the flat group, in order;
- a `GroupMessage` in any other group, or sent from the bot's own number, is ignored;
- a `DirectMessage` from a sender on `commands.direct_senders` is handed to
  `odin.commands.handle_direct`: its replies go back to the sender, and a notice of a change, if
  any, to the flat group. One from anyone else gets no answer and is logged with the sender's
  IDs, so an operator can find the one to add; one from the bot's own number is ignored.

ODIN's own sends normally reach it only as sync messages, which are never parsed into events;
ignoring its own number as well makes sure a reply such as `/text`'s ready-to-copy `/settext …`
can never be taken for a command.

Command replies are not recorded or retried: they are not part of the exactly-once weekly cycle.
A reply whose reactions matter (`TrackedReply`, the confirmation requests of `/cancel` and
`/introduce`) is tracked once sent, like the engine's flat poll, so that reactions to it are
stored. If Signal's answer cannot be read, it has no timestamp and stays untracked; the command
can simply be sent again. Replies to a direct message are never tracked: confirmations count
only in the flat group. Only the latest `/introduce` request counts: tracking it untracks the
earlier ones.
"""

import logging
from collections.abc import Coroutine
from typing import Any

from odin import commands
from odin.clock import Clock
from odin.commands import CommandContext, TrackedReply, ui
from odin.config import Config
from odin.engine import Account
from odin.overrides import effective_config
from odin.reactions import handle_reaction
from odin.signal import (
    DirectMessage,
    GroupMessage,
    ReactionEvent,
    SendResponseUnreadable,
    SignalClient,
)
from odin.store import MessageKind, Store

logger = logging.getLogger(__name__)


async def consume_events(
    client: SignalClient, store: Store, config: Config, account: Account, clock: Clock
) -> None:
    """Handle incoming events until the client's event stream ends.

    `config` is the TOML config; each event is judged by it with the overrides stored right then.
    Neither a crashing command nor a failed reply stops the consumer.
    """
    async for event in client.events():
        if isinstance(event, ReactionEvent):
            now = clock.now()
            handle_reaction(event, store, effective_config(config, store, now), now)
        elif (
            isinstance(event, GroupMessage)
            and event.group_id == account.flat_group_id
            and event.sender != account.number
        ):
            await _answer(event, client, store, config, account, clock)
        elif isinstance(event, DirectMessage) and event.sender != account.number:
            if config.commands.allows(event.sender, event.sender_uuid):
                await _answer_direct(event, client, store, config, account, clock)
            else:
                logger.info(
                    "ignoring a direct message from %s (UUID %s): not in commands.direct_senders",
                    event.sender,
                    event.sender_uuid or "unknown",
                )


async def _answer(
    message: GroupMessage,
    client: SignalClient,
    store: Store,
    config: Config,
    account: Account,
    clock: Clock,
) -> None:
    """Run the command in `message`, if it is one, and send its replies to the flat group."""
    ctx = _context(message.sender, message.sender_name, store, config, clock, direct=False)
    try:
        replies = commands.handle(message.text, ctx)
    except Exception:
        logger.exception("command %r failed", message.text.split(maxsplit=1)[0])
        replies = [ui.GENERIC_ERROR]
    for reply in replies:
        timestamp = await _send(client.send_group_message(account.flat_group_id, reply), "reply")
        if timestamp is not None and isinstance(reply, TrackedReply):
            _track(reply, timestamp, store, account)


async def _answer_direct(
    message: DirectMessage,
    client: SignalClient,
    store: Store,
    config: Config,
    account: Account,
    clock: Clock,
) -> None:
    """Answer `message` from an allowed sender: replies to them, a notice to the flat group."""
    ctx = _context(message.sender, message.sender_name, store, config, clock, direct=True)
    try:
        answer = commands.handle_direct(message.text, ctx)
    except Exception:
        logger.exception("command %r failed", message.text.split(maxsplit=1)[0])
        answer = commands.DirectAnswer([ui.GENERIC_ERROR])
    for reply in answer.replies:
        await _send(client.send_direct_message(message.sender, reply), "direct reply")
    if answer.notice is not None:
        await _send(client.send_group_message(account.flat_group_id, answer.notice), "notice")


def _context(
    sender: str, sender_name: str | None, store: Store, config: Config, clock: Clock, direct: bool
) -> CommandContext:
    now = clock.now()
    return CommandContext(
        base=config,
        config=effective_config(config, store, now),
        store=store,
        now=now,
        sender=sender,
        sender_name=sender_name,
        direct=direct,
    )


async def _send(send: Coroutine[Any, Any, int], what: str) -> int | None:
    """Await `send`; its timestamp, or None if it failed or the timestamp is unreadable."""
    try:
        return await send
    except SendResponseUnreadable as e:
        logger.warning("sent a command %s, but %s", what, e)
    except Exception:
        logger.exception("sending a command %s failed; not retried", what)
    return None


def _track(reply: TrackedReply, timestamp: int, store: Store, account: Account) -> None:
    if reply.kind is MessageKind.INTRODUCTION_REQUEST:
        # Replaces an earlier request, so a 👍 on an older preview posts nothing.
        with store.transaction():
            store.untrack_messages(reply.kind)
            store.track_message(
                reply.week, reply.kind, account.flat_group_id, account.number, timestamp
            )
        return
    # Checked after the send, with no await in between: two replies of the same kind sent at
    # once both pass the command's own check, and only the first one is kept.
    if store.tracked_message(reply.week, reply.kind) is not None:
        logger.warning("not tracking a second %s for week %s", reply.kind, reply.week)
        return
    store.track_message(reply.week, reply.kind, account.flat_group_id, account.number, timestamp)
