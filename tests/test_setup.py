import asyncio
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

from odib.app import DINNER_GROUP_KEY, FLAT_GROUP_KEY, serve
from odib.cli import main
from odib.clock import FixedClock
from odib.config import Env, load_config, load_env
from odib.setup import (
    CODE_REQUESTED_KEY,
    HELLO_KEY,
    OPERATOR_KEY,
    PIN_SET_KEY,
    PROFILE_KEY,
    TEST_KEY,
    SetupOptions,
    generate_pin,
    parse_captcha,
    parse_code,
    run_setup,
    setup_status,
)
from odib.signal import (
    AlreadyRegistered,
    CaptchaRequired,
    DirectMessage,
    FakeSignalAdmin,
    Group,
    RateLimited,
    RegistrationLocked,
    VoiceNotYetAllowed,
    VoiceRequired,
    WrongCode,
)
from odib.store import Store
from odib.terminal import ScriptedTerminal

EXAMPLE = Path(__file__).parent.parent / "config.example.toml"
CONFIG = load_config(EXAMPLE)
BERLIN = CONFIG.timezone

NUMBER = "+491701234567"
TIM = "+4915100000009"
ENV_VARS = {
    "SIGNAL_NUMBER": NUMBER,
    "SIGNAL_API_URL": "http://signal:8080",
    "ODIB_CONFIG": str(EXAMPLE),
    "ODIB_DB": "/data/odib.db",
}
ENV = load_env(ENV_VARS)

TOKEN = "signal-hcaptcha.5fad97ac-7d06-4e44-b18a-b950b20148ff.registration." + "P1_ab" * 40
CAPTCHA = "signalcaptcha://" + TOKEN
CAPTCHA_2 = CAPTCHA + "2"
PIN = "abcdefghjkmnpq23"

FLAT = Group(id="group.ZmxhdA==", internal_id="flat", name="WG")
DINNER = Group(id="group.ZGlubmVy", internal_id="dinner", name="Sonntagsessen")
DINNER_INVITED = Group(DINNER.id, DINNER.internal_id, DINNER.name, member=False)
# Listed by name: 1. Sonntagsessen (dinner), 2. WG (flat).
PICK = ["y", "2", "1"]


def local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=BERLIN)


START = local(6, 18, 5)  # Tuesday, the flat ask is due


@pytest.fixture(autouse=True)
def fixed_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("odib.setup.generate_pin", lambda: PIN)


@pytest.fixture
def store() -> Iterator[Store]:
    with Store(":memory:") as s:
        yield s


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(START)


def admin_with(**kwargs: object) -> FakeSignalAdmin:
    admin = FakeSignalAdmin(number=NUMBER, groups=[FLAT, DINNER], **kwargs)  # ty: ignore[invalid-argument-type]
    admin.inject_direct(DirectMessage(sender=TIM, text="Hi Odin", timestamp=1))
    return admin


def run(
    admin: FakeSignalAdmin,
    store: Store,
    clock: FixedClock,
    answers: Sequence[str],
    options: SetupOptions = SetupOptions(),  # noqa: B008
    env: Env = ENV,
) -> tuple[int, ScriptedTerminal]:
    terminal = ScriptedTerminal(answers)
    code = asyncio.run(run_setup(admin, store, CONFIG, env, terminal, clock, options))
    assert not store.setup_lock_held(clock.now()), "the lock is released on every exit path"
    return code, terminal


def registered_up_to_groups(store: Store) -> FakeSignalAdmin:
    """An account that has done steps 0-6."""
    admin = admin_with(accounts=[NUMBER])
    store.set_setting(PIN_SET_KEY, START.isoformat())
    store.set_setting(OPERATOR_KEY, TIM)
    store.set_setting(HELLO_KEY, START.isoformat())
    return admin


def last_question(terminal: ScriptedTerminal) -> str:
    return [line for line in terminal.output if line.endswith(": ")][-1]


def calls(admin: FakeSignalAdmin, method: str) -> list[dict[str, object]]:
    return [call.args for call in admin.calls_to(method)]


# --- input parsing -------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [CAPTCHA, TOKEN, f"  {CAPTCHA}\n", "SIGNALCAPTCHA://" + TOKEN])
def test_parse_captcha_accepts_link_or_token(raw: str) -> None:
    assert parse_captcha(raw) == TOKEN


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "123456",
        "signalcaptcha://",
        "https://signalcaptchas.org/x",
        "signal-short",
        TOKEN[:50] + " " + TOKEN[50:],
    ],
)
def test_parse_captcha_rejects_implausible_input(raw: str) -> None:
    assert parse_captcha(raw) is None


@pytest.mark.parametrize("raw", ["123-456", "123 456", "123456", " 123456 "])
def test_parse_code(raw: str) -> None:
    assert parse_code(raw) == "123456"


@pytest.mark.parametrize("raw", ["12345", "1234567", "123--456", "abc-def", ""])
def test_parse_code_rejects(raw: str) -> None:
    assert parse_code(raw) is None


def test_generated_pins_are_long_and_unambiguous() -> None:
    pins = {generate_pin() for _ in range(20)}
    assert len(pins) == 20
    for pin in pins:
        assert len(pin) == 16
        assert not set(pin) & set("0o1liI")
        assert pin == pin.lower()


# --- a fresh registration, end to end ------------------------------------------------------------


def test_fresh_setup_end_to_end(store: Store, clock: FixedClock) -> None:
    admin = admin_with()
    code, terminal = run(admin, store, clock, [CAPTCHA, "123-456", "pq23", TIM, *PICK, "y"])

    assert code == 0, terminal.text
    assert calls(admin, "register") == [{"captcha": TOKEN, "use_voice": False}]
    assert calls(admin, "verify") == [{"code": "123456", "pin": None}]
    assert admin.pin == PIN
    assert admin.profile == ("Odin 🍽️", None)
    [hello] = admin.sent_direct
    assert hello.recipient == TIM
    assert hello.text.startswith("Hallo, hier ist Odin 🍽️!")
    [test] = admin.sent
    assert test.group_id == FLAT.id
    assert "Bestätigt wird mit 👍" in test.text

    assert store.get_setting(FLAT_GROUP_KEY) == FLAT.id
    assert store.get_setting(DINNER_GROUP_KEY) == DINNER.id
    assert store.get_setting(OPERATOR_KEY) == TIM
    assert store.get_setting(CODE_REQUESTED_KEY) is None
    for key in (PIN_SET_KEY, PROFILE_KEY, HELLO_KEY, TEST_KEY):
        assert store.get_setting(key) == START.isoformat()
    # Only *that* a PIN was set is stored, never the PIN.
    for key in (PIN_SET_KEY, PROFILE_KEY, HELLO_KEY, TEST_KEY, OPERATOR_KEY):
        assert PIN not in (store.get_setting(key) or "")

    assert "signalcaptchas.org/registration/generate.html" in terminal.text
    assert f"    {PIN}" in terminal.output
    assert "ODIN is set up" in terminal.text
    assert "Back up the signal-cli data volume" in terminal.text


def test_a_finished_setup_runs_again_without_asking_anything(
    store: Store, clock: FixedClock
) -> None:
    admin = admin_with()
    assert run(admin, store, clock, [CAPTCHA, "123-456", "pq23", TIM, *PICK, "n"])[0] == 0
    before = len(admin.calls)

    code, terminal = run(admin, store, clock, [])

    assert code == 0, terminal.text
    new_calls = [call.method for call in admin.calls[before:]]
    assert new_calls == ["about", "list_accounts", "update_profile"]  # profile: always
    assert "already registered" in terminal.text
    assert admin.sent == []


def test_resume_after_each_step(store: Store, clock: FixedClock) -> None:
    admin = admin_with()

    # Stopped at the code prompt (Ctrl-D): the code was requested and is remembered.
    code, terminal = run(admin, store, clock, [CAPTCHA])
    assert code == 1
    assert "Run `odib setup` again to continue" in terminal.text
    assert store.get_setting(CODE_REQUESTED_KEY) == START.isoformat()

    # Resumed: the code that already arrived can be entered without a new captcha.
    code, terminal = run(admin, store, clock, ["123456"])
    assert code == 1
    assert "A verification code was requested at 2026-10-06 18:05" in terminal.text
    assert len(calls(admin, "register")) == 1
    assert NUMBER in admin.accounts
    assert "Type its last 4 characters" in last_question(terminal)

    # Registered: skipped from now on. The PIN is set, then stopped at the hello.
    code, terminal = run(admin, store, clock, ["pq23"])
    assert code == 1
    assert "already registered — skipping to step 4" in terminal.text
    assert admin.pin == PIN
    assert "Your own Signal number" in last_question(terminal)

    # The hello is answered; stopped while groups are listed.
    code, terminal = run(admin, store, clock, [TIM])
    assert code == 1
    assert "✓ The PIN was set at 2026-10-06 18:05" in terminal.text
    assert len(admin.sent_direct) == 1
    assert "Are both groups listed" in last_question(terminal)

    # Groups chosen; stopped at the test question.
    code, terminal = run(admin, store, clock, PICK)
    assert code == 1
    assert f"✓ {TIM} replied to ODIN" in terminal.text
    assert store.get_setting(FLAT_GROUP_KEY) == FLAT.id
    assert "test message" in last_question(terminal)

    code, terminal = run(admin, store, clock, ["n"])
    assert code == 0, terminal.text
    assert "✓ Flat group: group.ZmxhdA== (from database)" in terminal.text
    assert admin.sent == []
    assert len(calls(admin, "register")) == 1
    assert len(calls(admin, "verify")) == 1
    assert len(calls(admin, "set_pin")) == 1
    assert len(admin.sent_direct) == 1


def test_resumed_code_prompt_can_ask_for_a_new_code(store: Store, clock: FixedClock) -> None:
    admin = admin_with()
    store.set_setting(CODE_REQUESTED_KEY, START.isoformat())
    code, _ = run(admin, store, clock, ["", CAPTCHA, "123-456"])
    assert code == 1  # stops at the PIN
    assert len(calls(admin, "register")) == 1
    assert NUMBER in admin.accounts


# --- already registered --------------------------------------------------------------------------


def test_already_registered_skips_to_the_pin(store: Store, clock: FixedClock) -> None:
    admin = admin_with(accounts=[NUMBER])
    code, terminal = run(admin, store, clock, ["pq23", TIM, *PICK, "n"])
    assert code == 0, terminal.text
    assert calls(admin, "register") == []
    assert calls(admin, "verify") == []
    assert "already registered — skipping to step 4" in terminal.text
    assert "Step 1/9" not in terminal.text


def test_reregister_needs_confirmation(store: Store, clock: FixedClock) -> None:
    admin = admin_with(accounts=[NUMBER])
    code, terminal = run(admin, store, clock, ["yes"], SetupOptions(reregister=True))
    assert code == 1
    assert "Not confirmed — nothing changed." in terminal.text
    assert calls(admin, "register") == []


def test_reregister_explains_that_the_api_cannot_force_it(store: Store, clock: FixedClock) -> None:
    admin = admin_with(accounts=[NUMBER])
    admin.script("register", AlreadyRegistered(400, "Account is already registered"))
    code, terminal = run(
        admin, store, clock, ["reregister", CAPTCHA], SetupOptions(reregister=True)
    )
    assert code == 1
    assert len(calls(admin, "register")) == 1
    assert "cannot force a new registration" in terminal.text


# --- steps 1-3: captcha, register, code ---------------------------------------------------------


def test_a_bad_captcha_is_asked_again(store: Store, clock: FixedClock) -> None:
    admin = admin_with()
    admin.script("register", CaptchaRequired(400, "Invalid captcha given."))
    code, terminal = run(admin, store, clock, ["what?", CAPTCHA, CAPTCHA_2])
    assert code == 1  # stops at the code prompt
    assert "does not look like a captcha link" in terminal.text
    assert "Signal did not accept the captcha" in terminal.text
    assert [c["captcha"] for c in calls(admin, "register")] == [TOKEN, TOKEN + "2"]
    assert store.get_setting(CODE_REQUESTED_KEY) is not None


def test_voice_fallback(store: Store, clock: FixedClock) -> None:
    admin = admin_with()
    admin.script(
        "register",
        VoiceRequired(400, "Couldn't use SMS verification to register the specified number."),
    )
    code, terminal = run(admin, store, clock, [CAPTCHA, CAPTCHA_2, "123-456"])
    assert code == 1  # stops at the PIN
    assert calls(admin, "register") == [
        {"captcha": TOKEN, "use_voice": False},
        {"captcha": TOKEN + "2", "use_voice": True},
    ]
    assert clock.now() == START + timedelta(seconds=60)  # the countdown, on the fixed clock
    assert "  waiting 60 s …" in terminal.output
    assert "  waiting 10 s …" in terminal.output
    assert "by call" in terminal.text
    assert NUMBER in admin.accounts


def test_voice_not_yet_allowed_waits_and_retries(store: Store, clock: FixedClock) -> None:
    admin = admin_with()
    admin.script(
        "register",
        VoiceRequired(400, "Couldn't use SMS verification"),
        VoiceNotYetAllowed(400, "Before requesting voice verification you need to request SMS"),
    )
    code, _ = run(admin, store, clock, [CAPTCHA, CAPTCHA, CAPTCHA_2])
    assert code == 1
    assert [c["use_voice"] for c in calls(admin, "register")] == [False, True, True]
    assert clock.now() == START + timedelta(seconds=120)


def test_rate_limit_exits_cleanly(store: Store, clock: FixedClock) -> None:
    admin = admin_with()
    admin.script(
        "register",
        RateLimited(400, "Rate limit reached\nNext attempt may be tried at 2026-10-03T20:15:00Z"),
    )
    code, terminal = run(admin, store, clock, [CAPTCHA])
    assert code == 1
    assert "rate limit was reached" in terminal.text
    assert "The next attempt is possible at 2026-10-03T20:15:00Z." in terminal.text
    assert store.get_setting(CODE_REQUESTED_KEY) is None


def test_wrong_code_and_bad_format_are_asked_again(store: Store, clock: FixedClock) -> None:
    admin = admin_with()
    admin.script("verify", WrongCode(400, "Verify error: Invalid verification code"))
    code, terminal = run(admin, store, clock, [CAPTCHA, "12345", "111 111", "123 456"])
    assert code == 1  # stops at the PIN
    assert "A code has 6 digits" in terminal.text
    assert "Signal rejected the code (Verify error: Invalid verification code)" in terminal.text
    assert [c["code"] for c in calls(admin, "verify")] == ["111111", "123456"]


def test_new_code_starts_over(store: Store, clock: FixedClock) -> None:
    admin = admin_with()
    code, terminal = run(admin, store, clock, [CAPTCHA, "new", CAPTCHA_2, "123456"])
    assert code == 1  # stops at the PIN
    assert "Starting over with a new captcha." in terminal.text
    assert len(calls(admin, "register")) == 2
    assert NUMBER in admin.accounts


def test_registration_lock_exits_with_an_explanation(store: Store, clock: FixedClock) -> None:
    admin = admin_with()
    admin.script(
        "verify",
        RegistrationLocked(
            400,
            "Verification failed! This number is locked with a pin. "
            "Hours remaining until reset: 167",
        ),
    )
    code, terminal = run(admin, store, clock, [CAPTCHA, "123456"])
    assert code == 1
    assert "expires 7 days after that account was last active (167 hours remaining" in (
        terminal.text
    )
    assert NUMBER not in admin.accounts


def test_a_new_registration_voids_the_old_accounts_setup(store: Store, clock: FixedClock) -> None:
    admin = admin_with()
    store.set_setting(PIN_SET_KEY, START.isoformat())
    store.set_setting(HELLO_KEY, START.isoformat())
    run(admin, store, clock, [CAPTCHA, "123456"])
    assert store.get_setting(PIN_SET_KEY) is None
    assert store.get_setting(HELLO_KEY) is None


# --- steps 4-6: PIN, profile, hello -------------------------------------------------------------


def test_pin_confirmation_must_match(store: Store, clock: FixedClock) -> None:
    admin = admin_with(accounts=[NUMBER])
    code, terminal = run(admin, store, clock, ["abcd", "PQ23"])
    assert code == 1  # stops at the hello
    assert "That does not match" in terminal.text
    assert admin.pin == PIN


def test_own_pin_is_entered_twice_hidden_and_replaces_a_set_one(
    store: Store, clock: FixedClock
) -> None:
    admin = registered_up_to_groups(store)
    store.set_setting(FLAT_GROUP_KEY, FLAT.id)
    store.set_setting(DINNER_GROUP_KEY, DINNER.id)
    store.set_setting(TEST_KEY, START.isoformat())
    answers = ["123", "4711-0815", "4711-0816", "4711-0815", "4711-0815"]
    code, terminal = run(admin, store, clock, answers, SetupOptions(own_pin=True))
    assert code == 0, terminal.text
    assert terminal.secrets_asked == 5
    assert "Use at least 4 characters." in terminal.text
    assert "The two entries differ" in terminal.text
    assert calls(admin, "set_pin") == [{"pin": "4711-0815"}]
    assert "4711-0815" not in terminal.text


def test_profile_with_avatar_relative_to_the_config(
    tmp_path: Path, store: Store, clock: FixedClock
) -> None:
    (tmp_path / "odin.png").write_bytes(b"\x89PNG fake")
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        EXAMPLE.read_text().replace('# avatar = "odin.png"', 'avatar = "odin.png"')
    )
    config = load_config(config_file)
    admin = registered_up_to_groups(store)
    terminal = ScriptedTerminal([])
    asyncio.run(run_setup(admin, store, config, ENV, terminal, clock))
    assert admin.profile == ("Odin 🍽️", b"\x89PNG fake")
    assert "with the picture odin.png" in terminal.text


def test_hello_waits_for_the_operators_reply(store: Store, clock: FixedClock) -> None:
    admin = FakeSignalAdmin(number=NUMBER, groups=[FLAT, DINNER], accounts=[NUMBER])
    store.set_setting(PIN_SET_KEY, START.isoformat())

    async def scenario() -> int:
        terminal = ScriptedTerminal(["017 / 123", NUMBER, "+49 151 00000009"])
        setup = asyncio.create_task(run_setup(admin, store, CONFIG, ENV, terminal, clock))
        while not admin.sent_direct:
            await asyncio.sleep(0)
        admin.inject_direct(DirectMessage(sender="+4915100000001", text="Wer?", timestamp=2))
        for _ in range(20):
            await asyncio.sleep(0)
        assert store.get_setting(HELLO_KEY) is None  # someone else: still waiting
        admin.inject_direct(DirectMessage(sender=TIM, text="Hallo Odin", timestamp=3))
        code = await setup  # stops at the groups question
        assert "Enter it in international format" in terminal.text
        assert "That is ODIN's own number" in terminal.text
        assert "(Ignoring a message from +4915100000001.)" in terminal.text
        return code

    assert asyncio.run(scenario()) == 1
    assert admin.sent_direct[0].recipient == TIM
    assert store.get_setting(OPERATOR_KEY) == TIM
    assert store.get_setting(HELLO_KEY) == START.isoformat()


def test_hello_accepts_a_reply_from_a_hidden_number(store: Store, clock: FixedClock) -> None:
    admin = FakeSignalAdmin(number=NUMBER, groups=[FLAT, DINNER], accounts=[NUMBER])
    admin.inject_direct(
        DirectMessage(sender="5f3c8a2e-1b7d-4e0a-9c6f-2d8b4a1e7c90", text="hi", timestamp=1)
    )
    store.set_setting(PIN_SET_KEY, START.isoformat())
    code, terminal = run(admin, store, clock, [TIM])
    assert code == 1  # stops at the groups question
    assert "whose number is hidden" in terminal.text
    assert store.get_setting(HELLO_KEY) is not None


def test_redo_hello_offers_the_stored_number(store: Store, clock: FixedClock) -> None:
    admin = registered_up_to_groups(store)
    store.set_setting(FLAT_GROUP_KEY, FLAT.id)
    store.set_setting(DINNER_GROUP_KEY, DINNER.id)
    store.set_setting(TEST_KEY, START.isoformat())
    code, terminal = run(admin, store, clock, [""], SetupOptions(redo=frozenset({"hello"})))
    assert code == 0, terminal.text
    assert f"[{TIM}]" in terminal.text
    assert [m.recipient for m in admin.sent_direct] == [TIM]


# --- step 7: groups ------------------------------------------------------------------------------


def test_waits_for_groups_and_flags_invited_ones(store: Store, clock: FixedClock) -> None:
    admin = registered_up_to_groups(store)
    admin.script("list_groups", [], [FLAT, DINNER_INVITED], [FLAT, DINNER_INVITED])
    code, terminal = run(admin, store, clock, [*PICK, "n"])
    assert code == 0, terminal.text

    assert "ODIN is in no group yet. Waiting …" in terminal.text
    assert "  1. Sonntagsessen — INVITED, not a member" in terminal.output
    assert "ODIN is only invited to: Sonntagsessen" in terminal.text
    assert "accepts ODIN's message request" in terminal.text
    assert "remove it from the group and add it again" in terminal.text
    assert "  1. Sonntagsessen — member" in terminal.output
    # Polled on the clock: three empty or incomplete lists, 5 s apart; unchanged lists are not
    # printed again.
    assert len(calls(admin, "list_groups")) == 4
    assert clock.now() == START + timedelta(seconds=15)
    assert terminal.text.count("Groups ODIN sees:") == 2
    assert store.get_setting(FLAT_GROUP_KEY) == FLAT.id


def test_group_choice_is_validated(store: Store, clock: FixedClock) -> None:
    admin = registered_up_to_groups(store)
    choir = Group(id="group.Y2hvcg==", internal_id="choir", name="Chor", member=False)
    admin.groups = [FLAT, DINNER, choir]
    # Listed: 1. Chor (invited), 2. Sonntagsessen, 3. WG.
    answers = ["y", "x", "9", "1", "3", "3", "2", "n"]
    code, terminal = run(admin, store, clock, answers)
    assert code == 0, terminal.text
    assert "Enter a number from 1 to 3." in terminal.text
    assert "ODIN is only invited to Chor" in terminal.text
    assert "Flat and dinner group must be different groups." in terminal.text
    assert store.get_setting(FLAT_GROUP_KEY) == FLAT.id
    assert store.get_setting(DINNER_GROUP_KEY) == DINNER.id


def test_keep_waiting_until_the_list_changes(store: Store, clock: FixedClock) -> None:
    other = Group(id="group.b3RoZXI=", internal_id="other", name="Alte WG")
    admin = registered_up_to_groups(store)
    admin.script("list_groups", [FLAT, other], [FLAT, other])
    # Listed at last (the default list): 1. Sonntagsessen, 2. WG.
    code, terminal = run(admin, store, clock, ["n", *PICK, "n"])
    assert code == 0, terminal.text
    assert terminal.text.count("Are both groups listed") == 2  # not again for the same list
    assert store.get_setting(DINNER_GROUP_KEY) == DINNER.id


def test_env_override_of_both_groups(store: Store, clock: FixedClock) -> None:
    env = load_env({**ENV_VARS, "FLAT_GROUP_ID": "group.env-flat=", "DINNER_GROUP_ID": "group.e="})
    admin = registered_up_to_groups(store)
    code, terminal = run(admin, store, clock, ["y"], env=env)
    assert code == 0, terminal.text
    assert "FLAT_GROUP_ID and DINNER_GROUP_ID are set" in terminal.text
    assert calls(admin, "list_groups") == []
    assert store.get_setting(FLAT_GROUP_KEY) is None
    assert admin.sent[0].group_id == "group.env-flat="
    assert "group.env-flat= (from env var)" in terminal.text


def test_env_override_of_one_group_is_mentioned(store: Store, clock: FixedClock) -> None:
    env = load_env({**ENV_VARS, "DINNER_GROUP_ID": "group.e="})
    admin = registered_up_to_groups(store)
    code, terminal = run(admin, store, clock, [*PICK, "n"], env=env)
    assert code == 0, terminal.text
    assert "Note: DINNER_GROUP_ID is set (group.e=) and overrides this choice" in terminal.text
    assert store.get_setting(DINNER_GROUP_KEY) == DINNER.id
    assert "Dinner group: group.e= (from env var)" in terminal.text


def test_redo_groups(store: Store, clock: FixedClock) -> None:
    admin = registered_up_to_groups(store)
    store.set_setting(FLAT_GROUP_KEY, DINNER.id)  # chosen the wrong way round
    store.set_setting(DINNER_GROUP_KEY, FLAT.id)
    store.set_setting(TEST_KEY, START.isoformat())
    code, terminal = run(admin, store, clock, PICK, SetupOptions(redo=frozenset({"groups"})))
    assert code == 0, terminal.text
    assert store.get_setting(FLAT_GROUP_KEY) == FLAT.id
    assert store.get_setting(DINNER_GROUP_KEY) == DINNER.id


# --- preflight -----------------------------------------------------------------------------------


def test_preflight_needs_json_rpc_mode(store: Store, clock: FixedClock) -> None:
    admin = admin_with()
    admin.api_info = type(admin.api_info)(mode="native", version="0.9")
    code, terminal = run(admin, store, clock, [])
    assert code == 1
    assert "runs in 'native' mode; ODIN needs MODE=json-rpc" in terminal.text


def test_preflight_unreachable_api(store: Store, clock: FixedClock) -> None:
    admin = admin_with()
    admin.script("about", httpx.ConnectError("Connection refused"))
    code, terminal = run(admin, store, clock, [])
    assert code == 1
    assert "Cannot reach the Signal API at http://signal:8080" in terminal.text


# --- setup lock ----------------------------------------------------------------------------------


def test_a_fresh_lock_is_refused(store: Store, clock: FixedClock) -> None:
    assert store.acquire_setup_lock(clock.now() - timedelta(seconds=30)) is not None
    admin = admin_with()
    terminal = ScriptedTerminal([])
    code = asyncio.run(run_setup(admin, store, CONFIG, ENV, terminal, clock))
    assert code == 1
    assert "Another `odib setup` is running" in terminal.text
    assert admin.calls == []
    assert store.setup_lock_held(clock.now())  # the other holder's lock stays


def test_a_stale_lock_is_taken_over(store: Store, clock: FixedClock) -> None:
    assert store.acquire_setup_lock(clock.now() - timedelta(minutes=5)) is not None
    admin = admin_with()
    code, _ = run(admin, store, clock, [CAPTCHA])
    assert code == 1  # stopped at the code prompt, after doing its work
    assert len(calls(admin, "register")) == 1


def test_the_lock_is_held_while_the_wizard_runs(store: Store, clock: FixedClock) -> None:
    admin = admin_with()
    seen: list[bool] = []

    class Watching(ScriptedTerminal):
        async def prompt(self, question: str) -> str:
            seen.append(store.setup_lock_held(clock.now()))
            return await super().prompt(question)

    asyncio.run(run_setup(admin, store, CONFIG, ENV, Watching([CAPTCHA]), clock))
    assert seen == [True, True]
    assert not store.setup_lock_held(clock.now())


def test_the_heartbeat_keeps_the_lock_fresh(store: Store) -> None:
    clock = FixedClock(START)
    admin = admin_with()

    class Slow(ScriptedTerminal):
        async def prompt(self, question: str) -> str:
            clock.set(clock.now() + timedelta(minutes=10))  # long past the lock's TTL
            for _ in range(5):
                await asyncio.sleep(0)  # the heartbeat (interval 0) beats meanwhile
            assert store.setup_lock_held(clock.now())
            return await super().prompt(question)

    code = asyncio.run(
        run_setup(admin, store, CONFIG, ENV, Slow([]), clock, heartbeat_interval=timedelta(0))
    )
    assert code == 1


# --- --status ------------------------------------------------------------------------------------


def status(admin: FakeSignalAdmin, store: Store | None, env: Env = ENV) -> tuple[int, str]:
    terminal = ScriptedTerminal()
    code = asyncio.run(setup_status(admin, store, CONFIG, env, terminal, FixedClock(START)))
    return code, terminal.text


def test_status_of_a_fresh_setup() -> None:
    admin = FakeSignalAdmin(number=NUMBER)
    code, text = status(admin, None)
    assert code == 1
    assert "✓ Signal API: http://signal:8080 (json-rpc, 0.0-fake)" in text
    assert f"✗ Registered: {NUMBER} not registered" in text
    assert "✗ PIN set: no" in text
    assert "✗ Hello: no reply from the operator yet" in text
    assert "✗ Flat group: not chosen" in text
    assert "Not set up yet — run: odib setup" in text
    only_reads = {"about", "list_accounts"}
    assert {call.method for call in admin.calls} <= only_reads


def test_status_of_a_finished_setup(store: Store, clock: FixedClock) -> None:
    admin = admin_with()
    assert run(admin, store, clock, [CAPTCHA, "123-456", "pq23", TIM, *PICK, "n"])[0] == 0
    code, text = status(admin, store)
    assert code == 0, text
    assert f"✓ Registered: {NUMBER}" in text
    assert "✓ PIN set: 2026-10-06 18:05" in text
    assert f"✓ Hello: reply from {TIM} at 2026-10-06 18:05" in text
    assert "✓ Flat group: group.ZmxhdA== (from database) — WG" in text
    assert "✓ Dinner group: group.ZGlubmVy (from database) — Sonntagsessen" in text
    assert text.endswith("ODIN is set up.")


def test_status_flags_a_group_odin_is_no_longer_member_of(store: Store, clock: FixedClock) -> None:
    admin = admin_with()
    assert run(admin, store, clock, [CAPTCHA, "123-456", "pq23", TIM, *PICK, "n"])[0] == 0
    admin.groups = [FLAT]
    code, text = status(admin, store)
    assert code == 1
    assert "✗ Dinner group: group.ZGlubmVy (from database) — ODIN is not in this group" in text


def test_status_shows_a_pending_code_and_an_unreachable_api(store: Store) -> None:
    store.set_setting(CODE_REQUESTED_KEY, START.isoformat())
    admin = FakeSignalAdmin(number=NUMBER)
    code, text = status(admin, store)
    assert "a code was requested at 2026-10-06 18:05" in text

    admin.script("about", httpx.ConnectError("Connection refused"))
    code, text = status(admin, store)
    assert code == 1
    assert "✗ Signal API: not reachable at http://signal:8080 (Connection refused)" in text


# --- odib run picks up the finished setup --------------------------------------------------------


def test_odib_run_starts_once_the_wizard_finishes(store: Store, clock: FixedClock) -> None:
    admin = admin_with()
    terminal = ScriptedTerminal([CAPTCHA, "123-456", "pq23", TIM, *PICK, "n"])

    async def until(condition: Callable[[], bool]) -> None:
        for _ in range(1_000):
            if condition():
                return
            await asyncio.sleep(0)
        raise AssertionError("condition never became true")

    async def scenario() -> None:
        stop = asyncio.Event()
        bot = asyncio.create_task(
            serve(
                CONFIG,
                store,
                admin,
                ENV,
                clock,
                stop,
                check_interval=timedelta(0),
                tick_interval=timedelta(0),
                admin=admin,
            )
        )
        for _ in range(20):
            await asyncio.sleep(0)
        assert admin.sent == []  # not registered, no groups: waiting

        assert await run_setup(admin, store, CONFIG, ENV, terminal, clock) == 0
        await until(lambda: len(admin.sent) == 1)
        stop.set()
        await bot

    asyncio.run(scenario())
    [flat_ask] = admin.sent
    assert flat_ask.group_id == FLAT.id
    assert flat_ask.text.startswith("Findet am Sonntag das offene Abendessen statt?")


# --- CLI -----------------------------------------------------------------------------------------


def test_status_cannot_be_combined(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit:
        main(["setup", "--status", "--pin"], ENV_VARS)
    assert exit.value.code == 2
    assert "--status cannot be combined" in capsys.readouterr().err


def test_redo_rejects_unknown_steps(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit:
        main(["setup", "--redo", "captcha"], ENV_VARS)
    assert exit.value.code == 2
    assert "invalid choice: 'captcha'" in capsys.readouterr().err
