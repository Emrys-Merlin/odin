import asyncio

from odib.signal import FakeSignalClient, Group, ReactionEvent, SentMessage, SignalClient


def reaction(emoji: str = "👍", is_remove: bool = False) -> ReactionEvent:
    return ReactionEvent(
        emoji=emoji,
        reactor="+4915100000002",
        target_author="+490000000000",
        target_timestamp=1000,
        group_id="group.flat=",
        is_remove=is_remove,
        timestamp=2000,
    )


def test_records_sent_messages_with_increasing_timestamps() -> None:
    fake = FakeSignalClient()

    async def send() -> list[int]:
        return [
            await fake.send_group_message("group.flat=", "Essen am Sonntag?"),
            await fake.send_group_message("group.dinner=", "Abgesagt / Cancelled"),
        ]

    assert asyncio.run(send()) == [1000, 1001]
    assert fake.sent == [
        SentMessage("group.flat=", "Essen am Sonntag?", 1000),
        SentMessage("group.dinner=", "Abgesagt / Cancelled", 1001),
    ]


def test_lists_configured_groups() -> None:
    groups = [Group(id="group.flat=", internal_id="flat=", name="WG")]
    fake: SignalClient = FakeSignalClient(groups=groups)
    assert asyncio.run(fake.list_groups()) == groups


def test_yields_injected_events_until_closed() -> None:
    fake = FakeSignalClient()
    events = [reaction(), reaction(is_remove=True), reaction("❤️")]
    for event in events:
        fake.inject(event)
    fake.close()

    async def collect() -> list[ReactionEvent]:
        return [event async for event in fake.events()]

    assert asyncio.run(collect()) == events


def test_events_wait_for_injection() -> None:
    async def scenario() -> ReactionEvent:
        fake = FakeSignalClient()
        stream = fake.events()
        pending = asyncio.ensure_future(anext(stream))
        await asyncio.sleep(0)
        assert not pending.done()
        fake.inject(reaction())
        return await pending

    assert asyncio.run(scenario()) == reaction()
