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
"""

import logging

from odin import commands
from odin.clock import Clock
from odin.commands import CommandContext, ui
from odin.config import Config
from odin.engine import Account
from odin.overrides import effective_config
from odin.reactions import handle_reaction
from odin.signal import GroupMessage, ReactionEvent, SignalClient
from odin.store import Store

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
            handle_reaction(event, store, effective_config(config, store), clock.now())
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
    ctx = CommandContext(
        base=config,
        config=effective_config(config, store),
        store=store,
        now=clock.now(),
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
            await client.send_group_message(account.flat_group_id, reply)
        except Exception:
            logger.exception("sending a command reply failed; not retried")
