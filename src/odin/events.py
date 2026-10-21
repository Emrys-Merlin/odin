"""The bot's single consumer of incoming Signal events: reactions and chat commands.

Signal fans every event out to each WebSocket client, so the bot opens one event stream and
dispatches from it:

- a `ReactionEvent` is applied to the store (`odin.reactions.handle_reaction`);
- a `GroupMessage` in the flat group is handed to the chat commands (`odin.commands.handle`)
  and each reply is sent back to the flat group, in order;
- a `GroupMessage` in any other group, or sent from the bot's own number, is ignored.

ODIN's own sends normally reach it only as sync messages, which are never parsed into events;
ignoring its own number as well makes sure a reply such as `/text`'s ready-to-copy `/settext …`
can never be taken for a command.

Command replies are not recorded or retried: they are not part of the exactly-once weekly cycle.
A reply whose reactions matter (`TrackedReply`, the confirmation requests of `/cancel` and
`/introduce`) is tracked once sent, like the engine's flat poll, so that reactions to it are
stored. If Signal's answer cannot be read, it has no timestamp and stays untracked; the command
can simply be sent again. Only the latest `/introduce` request counts: tracking it untracks the
earlier ones.
"""

import logging

from odin import commands
from odin.clock import Clock
from odin.commands import CommandContext, TrackedReply, ui
from odin.config import Config
from odin.engine import Account
from odin.overrides import effective_config
from odin.reactions import handle_reaction
from odin.signal import GroupMessage, ReactionEvent, SendResponseUnreadable, SignalClient
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


async def _answer(
    message: GroupMessage,
    client: SignalClient,
    store: Store,
    config: Config,
    account: Account,
    clock: Clock,
) -> None:
    """Run the command in `message`, if it is one, and send its replies to the flat group."""
    now = clock.now()
    ctx = CommandContext(
        base=config,
        config=effective_config(config, store, now),
        store=store,
        now=now,
        sender=message.sender,
        sender_name=message.sender_name,
    )
    try:
        replies = commands.handle(message.text, ctx)
    except Exception:
        logger.exception("command %r failed", message.text.split(maxsplit=1)[0])
        replies = [ui.GENERIC_ERROR]
    for reply in replies:
        try:
            timestamp = await client.send_group_message(account.flat_group_id, reply)
        except SendResponseUnreadable as e:
            logger.warning("sent a command reply, but %s", e)
            continue
        except Exception:
            logger.exception("sending a command reply failed; not retried")
            continue
        if isinstance(reply, TrackedReply):
            _track(reply, timestamp, store, account)


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
