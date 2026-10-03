import asyncio

import pytest

from odib.signal import (
    AdminCall,
    AlreadyRegistered,
    ApiInfo,
    DirectMessage,
    FakeSignalAdmin,
    FakeSignalClient,
    Group,
    ReactionEvent,
    SentDirectMessage,
    SentMessage,
    SignalAdmin,
    SignalClient,
    VoiceRequired,
)


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


NUMBER = "+4915100000001"


def test_admin_satisfies_both_protocols() -> None:
    admin: SignalAdmin = FakeSignalAdmin()
    client: SignalClient = FakeSignalAdmin()
    assert admin
    assert client


def test_admin_defaults_succeed_and_are_recorded() -> None:
    fake = FakeSignalAdmin(number=NUMBER)

    async def scenario() -> None:
        assert await fake.about() == ApiInfo(mode="json-rpc", version="0.0-fake")
        assert await fake.list_accounts() == []
        await fake.register("token")
        await fake.verify("123456")
        assert await fake.list_accounts() == [NUMBER]
        await fake.set_pin("4711")
        await fake.update_profile("Odin 🍽️", b"png")

    asyncio.run(scenario())
    assert fake.pin == "4711"
    assert fake.profile == ("Odin 🍽️", b"png")
    assert fake.calls == [
        AdminCall("about"),
        AdminCall("list_accounts"),
        AdminCall("register", {"captcha": "token", "use_voice": False}),
        AdminCall("verify", {"code": "123456", "pin": None}),
        AdminCall("list_accounts"),
        AdminCall("set_pin", {"pin": "4711"}),
        AdminCall("update_profile", {"name": "Odin 🍽️", "avatar": b"png"}),
    ]
    assert fake.calls_to("list_accounts") == [AdminCall("list_accounts")] * 2


def test_scripted_outcomes_are_used_in_order_then_defaults() -> None:
    fake = FakeSignalAdmin(number=NUMBER)
    fake.script("register", VoiceRequired(400, "use voice"), None)
    fake.script("list_accounts", ["+4900"])

    async def scenario() -> None:
        with pytest.raises(VoiceRequired):
            await fake.register("token")
        await fake.register("token", use_voice=True)
        await fake.register("token")
        assert await fake.list_accounts() == ["+4900"]
        assert await fake.list_accounts() == []

    asyncio.run(scenario())
    assert [call.args["use_voice"] for call in fake.calls_to("register")] == [False, True, False]


def test_scripted_error_skips_default_effect() -> None:
    fake = FakeSignalAdmin(number=NUMBER)
    fake.script("verify", AlreadyRegistered(400, "Account is already registered"))
    with pytest.raises(AlreadyRegistered):
        asyncio.run(fake.verify("123456"))
    assert fake.accounts == []


def test_script_unknown_method_fails() -> None:
    with pytest.raises(ValueError):
        FakeSignalAdmin().script("regsiter", None)


def test_direct_messages_share_timestamps_with_group_messages() -> None:
    fake = FakeSignalAdmin()

    async def send() -> list[int]:
        return [
            await fake.send_group_message("group.flat=", "Hallo WG"),
            await fake.send_direct_message("+4915100000002", "Hallo Tim"),
        ]

    assert asyncio.run(send()) == [1000, 1001]
    assert fake.sent_direct == [SentDirectMessage("+4915100000002", "Hallo Tim", 1001)]


def test_group_membership_can_change_between_calls() -> None:
    invited = Group(id="group.dinner=", internal_id="dinner=", name="Essen", member=False)
    fake = FakeSignalAdmin(groups=[invited])
    assert asyncio.run(fake.list_groups()) == [invited]
    fake.groups = [Group(id="group.dinner=", internal_id="dinner=", name="Essen")]
    [group] = asyncio.run(fake.list_groups())
    assert group.member
    assert fake.calls_to("list_groups") == [AdminCall("list_groups")] * 2


def test_yields_injected_direct_messages_until_closed() -> None:
    fake = FakeSignalAdmin()
    messages = [DirectMessage("+4915100000002", "ja", 1), DirectMessage("uuid", "nein", 2)]
    for message in messages:
        fake.inject_direct(message)
    fake.inject(reaction())
    fake.close()

    async def collect() -> tuple[list[DirectMessage], list[ReactionEvent]]:
        return (
            [message async for message in fake.direct_messages()],
            [event async for event in fake.events()],
        )

    assert asyncio.run(collect()) == (messages, [reaction()])
