"""/emoji: show and change the reactions for coming (attend) and helping cook (cook)."""

from datetime import datetime

from helpers import local

from odin.commands import CommandContext, handle
from odin.commands import emoji as emoji_command
from odin.commands.ui import RESET, SAVED
from odin.config import Config, parse_config
from odin.overrides import COOK_EMOJI_KEY, EMOJI_KEY, effective_config
from odin.store import Store

TEMPLATES = {
    "flat_ask": "ASK",
    "nudge": "NUDGE",
    "cancellation": "ABGESAGT\n\nCANCELLED",
    "announcement": "ESSEN\n\nDINNER",
    "tally": "TALLY {count}",
    "hello": "HELLO",
    "flat_test": "TEST",
}
CONFIG = parse_config({"templates": TEMPLATES})
ANNA = "+4915100000001"
NOW = local(6, 9)

ATTEND_LINE = emoji_command.LINES[EMOJI_KEY]
COOK_LINE = emoji_command.LINES[COOK_EMOJI_KEY]


def run(store: Store, text: str, now: datetime = NOW, base: Config = CONFIG) -> list[str]:
    ctx = CommandContext(
        base=base,
        config=effective_config(base, store, now),
        store=store,
        now=now,
        sender=ANNA,
        sender_name="Anna",
    )
    return handle(text, ctx)


def test_shows_both_emojis(store: Store) -> None:
    assert run(store, "/emoji") == [
        "\n".join(
            [
                emoji_command.HEADLINE,
                ATTEND_LINE.format(emoji="👍"),
                COOK_LINE.format(emoji="🍳"),
            ]
        )
    ]


def test_sets_the_cook_emoji(store: Store) -> None:
    [reply] = run(store, "/emoji cook 🧑‍🍳")
    assert reply == "\n".join(
        [
            SAVED,
            emoji_command.HEADLINE,
            ATTEND_LINE.format(emoji="👍"),
            COOK_LINE.format(emoji="🧑‍🍳") + " ✏️ 06.10. von Anna",
            emoji_command.FROM_NEXT_MESSAGE,
        ]
    )
    assert store.overrides()[COOK_EMOJI_KEY].value == "🧑‍🍳"
    assert effective_config(CONFIG, store, NOW).cook_emoji == "🧑‍🍳"


def test_sets_the_attend_emoji(store: Store) -> None:
    run(store, "/emoji ATTEND 🙋")
    config = effective_config(CONFIG, store, NOW)
    assert (config.emoji, config.cook_emoji) == ("🙋", "🍳")
    assert config.placeholder_values()["emoji"] == "🙋"


def test_refuses_the_other_emoji(store: Store) -> None:
    assert run(store, "/emoji cook 👍🏽") == [
        emoji_command.SAME_AS_OTHER.format(value="👍🏽", name="attend", other="👍")
    ]
    assert run(store, "/emoji attend 🍳") == [
        emoji_command.SAME_AS_OTHER.format(value="🍳", name="cook", other="🍳")
    ]
    assert store.overrides() == {}


def test_refuses_what_is_not_an_emoji(store: Store) -> None:
    assert run(store, "/emoji cook yes") == [emoji_command.NOT_AN_EMOJI.format(value="yes")]
    assert store.overrides() == {}


def test_usage_errors(store: Store) -> None:
    for text in ("/emoji cook", "/emoji cook 🍳 🔪", "/emoji dessert 🍰", "/emoji reset all"):
        assert run(store, text) == [emoji_command.USAGE], text


def test_reset_one(store: Store) -> None:
    run(store, "/emoji cook 🔪")
    run(store, "/emoji attend 🙋")
    [reply] = run(store, "/emoji reset cook")
    assert reply.splitlines()[0] == RESET
    assert COOK_LINE.format(emoji="🍳") in reply.splitlines()
    assert list(store.overrides()) == [EMOJI_KEY]


def test_reset_both(store: Store) -> None:
    run(store, "/emoji cook 🔪")
    run(store, "/emoji attend 🙋")
    run(store, "/emoji reset")
    assert store.overrides() == {}


def test_reset_without_a_change(store: Store) -> None:
    assert run(store, "/emoji reset") == [emoji_command.NOT_OVERRIDDEN]


def test_reset_that_would_clash_is_refused(store: Store) -> None:
    # Attend is 🍳 now; resetting cook would make it 🍳 too.
    run(store, "/emoji cook 🔪")
    run(store, "/emoji attend 🍳")
    assert run(store, "/emoji reset cook") == [
        emoji_command.RESET_CONFLICT.format(name="cook", value="🍳")
    ]
    assert set(store.overrides()) == {EMOJI_KEY, COOK_EMOJI_KEY}
