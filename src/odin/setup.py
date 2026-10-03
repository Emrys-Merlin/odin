"""`odin setup`: the interactive wizard that registers ODIN's number and picks its groups.

Steps (see issue #25): 0 preflight, 1 captcha, 2 register, 3 code, 4 PIN, 5 profile, 6 hello,
7 groups, 8 test message, 9 done. Every step first looks at the real state (the Signal API and
the settings table) and is skipped when it is done, so the wizard can be stopped at any point and
run again later; it continues where it stopped.

What the wizard remembers lives in the settings table (`SETUP_KEYS`): when a code was requested,
when the PIN was set (never the PIN itself), when the profile was applied, the operator's number
and when their reply to the hello arrived, whether the test step was answered, and the chosen
groups (`odin.app.FLAT_GROUP_KEY` / `DINNER_GROUP_KEY`, which the bot reads).

`setup_status` is the read-only `--status` view of the same state.
"""

import asyncio
import contextlib
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

import httpx

from odin.app import DINNER_GROUP_KEY, FLAT_GROUP_KEY, Source, resolve_account
from odin.clock import Clock
from odin.config import Config, Env, Template, is_e164
from odin.signal import (
    AlreadyRegistered,
    CaptchaRequired,
    DirectMessage,
    Group,
    RateLimited,
    RegistrationLocked,
    SignalAdmin,
    SignalApiError,
    SignalClient,
    VoiceNotYetAllowed,
    VoiceRequired,
    WrongCode,
    WrongPin,
)
from odin.store import SETUP_LOCK_TTL, Store
from odin.terminal import Terminal

# Settings keys. Times are stored as ISO 8601 (UTC).
CODE_REQUESTED_KEY = "setup.code_requested_at"
PIN_SET_KEY = "setup.pin_set_at"
PROFILE_KEY = "setup.profile_applied_at"
OPERATOR_KEY = "setup.operator_number"
HELLO_KEY = "setup.hello_reply_at"
TEST_KEY = "setup.test_answered_at"
SETUP_KEYS = (CODE_REQUESTED_KEY, PIN_SET_KEY, PROFILE_KEY, OPERATOR_KEY, HELLO_KEY, TEST_KEY)

# Steps that `--redo` can repeat although they are done. Registration cannot be repeated (the
# REST API cannot re-register an account), and the profile is applied on every run anyway.
REDO_STEPS = ("pin", "hello", "groups", "test")

CAPTCHA_URL = "https://signalcaptchas.org/registration/generate.html"
CAPTCHA_SCHEME = "signalcaptcha://"
# Real tokens are long (a few hundred to a few thousand characters); this only catches pasting
# the wrong thing.
CAPTCHA_LENGTH = range(20, 20_000)
# Signal wants a minute between the SMS request and the voice call.
VOICE_WAIT = timedelta(seconds=60)
COUNTDOWN_STEP = timedelta(seconds=10)
GROUP_POLL_INTERVAL = timedelta(seconds=5)
# Well within SETUP_LOCK_TTL, so the lock never looks stale while the wizard runs.
HEARTBEAT_INTERVAL = timedelta(seconds=30)
assert HEARTBEAT_INTERVAL < SETUP_LOCK_TTL

# 31 characters without look-alikes (no 0/o, 1/l/i); 16 of them are about 79 bits.
PIN_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
PIN_LENGTH = 16
MIN_OWN_PIN_LENGTH = 4

RUN_AGAIN = "Run `odin setup` again to continue; finished steps are skipped."


class SetupSignal(SignalAdmin, SignalClient, Protocol):
    """What the wizard needs from Signal: account administration plus sending to a group."""


@dataclass(frozen=True)
class SetupOptions:
    own_pin: bool = False  # ask for a PIN instead of generating one; also re-sets a set PIN
    redo: frozenset[str] = field(default_factory=frozenset)  # subset of REDO_STEPS


class SetupExit(Exception):
    """End the wizard with ``message`` (already explained, not a crash)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# --- input parsing -------------------------------------------------------------------------------


def parse_captcha(raw: str) -> str | None:
    """The captcha token from a pasted "Open Signal" link or bare token; None if implausible."""
    token = raw.strip()
    if token.lower().startswith(CAPTCHA_SCHEME):
        token = token[len(CAPTCHA_SCHEME) :].strip()
    if (
        not token.startswith("signal-")
        or re.search(r"\s", token)
        or len(token) not in CAPTCHA_LENGTH
    ):
        return None
    return token


def parse_code(raw: str) -> str | None:
    """The 6-digit verification code from ``123-456``, ``123 456`` or ``123456``."""
    match = re.fullmatch(r"(\d{3})[- ]?(\d{3})", raw.strip())
    return match.group(1) + match.group(2) if match else None


def generate_pin() -> str:
    return "".join(secrets.choice(PIN_ALPHABET) for _ in range(PIN_LENGTH))


# --- the wizard ----------------------------------------------------------------------------------


async def run_setup(
    admin: SetupSignal,
    store: Store,
    config: Config,
    env: Env,
    terminal: Terminal,
    clock: Clock,
    options: SetupOptions = SetupOptions(),  # noqa: B008 - frozen, so sharing it is safe
    heartbeat_interval: timedelta = HEARTBEAT_INTERVAL,
) -> int:
    """Run the wizard; returns the exit code (0: ODIN is set up).

    The wizard holds the setup lock for its whole run, so `odin run` neither sends nor consumes
    events meanwhile. Strictly the lock is only needed for the hello step: signal-cli-rest-api
    (json-rpc mode) fans every received message out to *all* WebSocket clients of the number
    without waiting, so the bot would see the operator's reply too, and a client that is busy
    at that moment misses it. Holding it throughout keeps the bot from posting into a group
    that is being chosen right now. The heartbeat runs in its own task (prompts read input in a
    thread, so it keeps beating); a killed wizard's lock goes stale after SETUP_LOCK_TTL.
    """
    token = store.acquire_setup_lock(clock.now())
    if token is None:
        terminal.print(
            "Another `odin setup` is running right now. Finish that one first. (If it was "
            f"killed, its lock expires within {SETUP_LOCK_TTL.seconds // 60} minutes.)"
        )
        return 1
    wizard = _Wizard(admin, store, config, env, terminal, clock, options, token)
    work = asyncio.create_task(wizard.run())
    heartbeat = asyncio.create_task(_heartbeat(store, token, clock, heartbeat_interval))
    try:
        await asyncio.wait({work, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
        if not work.done():
            terminal.print()
            terminal.print("Lost the setup lock (did another `odin setup` take over?). Stopping.")
            return 1
        return work.result()
    finally:
        for task in (work, heartbeat):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        store.release_setup_lock(token)


async def _heartbeat(store: Store, token: str, clock: Clock, interval: timedelta) -> None:
    """Refresh the lock every `interval`; returns once the lock is no longer ours."""
    while True:
        await asyncio.sleep(interval.total_seconds())
        if not store.refresh_setup_lock(token, clock.now()):
            return


class _Wizard:
    def __init__(
        self,
        admin: SetupSignal,
        store: Store,
        config: Config,
        env: Env,
        terminal: Terminal,
        clock: Clock,
        options: SetupOptions,
        token: str,
    ) -> None:
        self.admin = admin
        self.store = store
        self.config = config
        self.env = env
        self.t = terminal
        self.clock = clock
        self.options = options
        self.token = token

    async def run(self) -> int:
        try:
            registered = await self.preflight()
            if not registered:
                await self.register()
            await self.pin()
            await self.profile()
            await self.hello()
            await self.groups()
            await self.test()
            self.done()
        except SetupExit as e:
            self.t.print()
            self.t.print(e.message)
            return 1
        except EOFError:
            self.t.print()
            self.t.print(f"Stopped. {RUN_AGAIN}")
            return 1
        except (httpx.HTTPError, SignalApiError) as e:
            self.t.print()
            self.t.print(f"The Signal API call failed: {e}")
            self.t.print(RUN_AGAIN)
            return 1
        return 0

    # Step 0

    async def preflight(self) -> bool:
        """Check the API; returns whether the number is registered already."""
        self.step(0, "Preflight")
        url = self.env.signal_api_url
        try:
            info = await self.admin.about()
        except httpx.HTTPError as e:
            raise SetupExit(
                f"Cannot reach the Signal API at {url} ({e}). Is the signal-cli-rest-api "
                f"container running? {RUN_AGAIN}"
            ) from None
        if info.mode != "json-rpc":
            raise SetupExit(
                f"The Signal API at {url} runs in {info.mode!r} mode; ODIN needs MODE=json-rpc. "
                "Fix the container's environment and run `odin setup` again."
            )
        number = self.env.signal_number
        registered = number in await self.admin.list_accounts()
        self.t.print(f"Signal API {url} is up (json-rpc, version {info.version}).")
        if registered:
            self.t.print(f"✓ {number} is already registered — skipping to step 4.")
        else:
            self.t.print(f"{number} is not registered yet.")
        return registered

    # Steps 1-3

    async def register(self) -> None:
        requested = self.store.get_setting(CODE_REQUESTED_KEY)
        if requested is not None:
            self.step(3, "Code")
            self.t.print(
                f"A verification code was requested at {self.local(requested)}. If you got it, "
                "enter it now."
            )
            if await self.enter_code(resumed=True):
                return
        while True:
            await self.request_code()
            if await self.enter_code(resumed=False):
                return
            self.t.print("Starting over with a new captcha.")

    async def request_code(self) -> None:
        self.step(1, "Captcha")
        self.t.print(
            f"Open {CAPTCHA_URL} in a desktop browser and solve the captcha. Then right-click "
            "“Open Signal” and copy the link (it starts with signalcaptcha://)."
        )
        captcha = await self.captcha()
        self.step(2, "Register")
        use_voice = False
        while True:
            try:
                await self.admin.register(captcha=captcha, use_voice=use_voice)
                break
            except CaptchaRequired:
                self.t.print(
                    "Signal did not accept the captcha (invalid or expired — it is only valid "
                    f"for a short time). Solve a new one at {CAPTCHA_URL}."
                )
            except VoiceRequired:
                self.t.print("Signal cannot send an SMS to this number; it will call instead.")
                await self.countdown(VOICE_WAIT)
                use_voice = True
                self.t.print(f"Solve a fresh captcha at {CAPTCHA_URL} for the call.")
            except VoiceNotYetAllowed:
                self.t.print("Signal wants a minute between the SMS request and the call.")
                await self.countdown(VOICE_WAIT)
                self.t.print(f"Solve a fresh captcha at {CAPTCHA_URL}.")
            except RateLimited as e:
                when = (
                    f"The next attempt is possible at {e.next_attempt}."
                    if e.next_attempt
                    else "Wait a few hours before trying again."
                )
                raise SetupExit(
                    "Signal's rate limit was reached (too many registration attempts for this "
                    f"number). {when}\nSignal said: {e.message}\n{RUN_AGAIN}"
                ) from None
            except AlreadyRegistered:
                raise SetupExit(
                    "Signal says the account is already registered. signal-cli-rest-api cannot "
                    "force a new registration of an existing account; to really start over, "
                    "ODIN's account data would have to be removed from the signal-cli volume "
                    'first (this throws away its keys). See "What the wizard cannot do" in '
                    "docs/runbooks/signal-registration.md."
                ) from None
            captcha = await self.captcha()
        self.store.set_setting(CODE_REQUESTED_KEY, self.clock.now().isoformat())
        how = "call" if use_voice else "SMS"
        self.t.print(f"✓ Signal is sending a verification code by {how} to the SIM's phone.")

    async def captcha(self) -> str:
        while True:
            token = parse_captcha(await self.t.prompt("Captcha link: "))
            if token is not None:
                return token
            self.t.print(
                "That does not look like a captcha link. It starts with "
                "signalcaptcha://signal- and has no spaces. Try again."
            )

    async def enter_code(self, resumed: bool) -> bool:
        """Verify a code; returns False if the operator wants a new one instead."""
        self.step(3, "Code")
        new = "press Enter" if resumed else "type 'new'"
        while True:
            raw = (
                await self.t.prompt(f"Code, e.g. 123-456 ({new} to request a new one): ")
            ).strip()
            if raw.lower() == "new" or (resumed and not raw):
                self.store.delete_setting(CODE_REQUESTED_KEY)
                return False
            code = parse_code(raw)
            if code is None:
                self.t.print("A code has 6 digits, like 123-456 or 123456. Try again.")
                continue
            try:
                await self.admin.verify(code)
                pin_used = False
            except WrongCode as e:
                self.t.print(
                    f"Signal rejected the code ({e.message}). Check it and type it again, or "
                    f"{new} to start over."
                )
                continue
            except RegistrationLocked as e:
                await self.unlock(code, e)
                pin_used = True
            break
        # A new registration means a new account: what was set up for the old one is void.
        # Unlocked with ODIN's PIN, the account has that PIN already; step 4 keeps it.
        with self.store.transaction():
            for key in (CODE_REQUESTED_KEY, PIN_SET_KEY, PROFILE_KEY, HELLO_KEY):
                self.store.delete_setting(key)
            if pin_used:
                self.store.set_setting(PIN_SET_KEY, self.clock.now().isoformat())
        self.t.print(f"✓ {self.env.signal_number} is registered.")
        return True

    async def unlock(self, code: str, locked: RegistrationLocked) -> None:
        """Verify ``code`` again with the PIN of the registration lock, if the operator has it."""
        hours = locked.hours_remaining
        remaining = f" ({hours} hours remaining, says Signal)" if hours is not None else ""
        self.t.print(
            "This number is protected by a registration lock (PIN). Either it is ODIN's own "
            "lock — ODIN's account was lost and is being registered again — and its PIN is in "
            "the password manager, or it is the lock of a previous Signal account on this "
            "number, whose PIN you do not have."
        )
        while True:
            pin = await self.t.secret("ODIN's PIN (press Enter if you do not have it): ")
            if not pin:
                raise SetupExit(
                    "This number is still protected by the registration lock (PIN) of a "
                    "previous Signal account. The lock expires 7 days after that account was "
                    f"last active{remaining}. Run `odin setup` again after that."
                ) from None
            try:
                await self.admin.verify(code, pin)
            except WrongPin as e:
                tries = e.tries_remaining
                left = f" ({tries} tries remaining, says Signal)" if tries is not None else ""
                self.t.print(
                    f"Signal rejected the PIN{left}. Check the password manager and type it "
                    "again, or press Enter to stop."
                )
                continue
            return

    async def countdown(self, total: timedelta) -> None:
        left = total
        while left > timedelta(0):
            self.t.print(f"  waiting {left.seconds} s …")
            step = min(COUNTDOWN_STEP, left)
            await self.sleep(step)
            left -= step

    # Step 4

    async def pin(self) -> None:
        self.step(4, "PIN")
        set_at = self.store.get_setting(PIN_SET_KEY)
        if set_at is not None and not self.options.own_pin and "pin" not in self.options.redo:
            self.t.print(f"✓ The PIN was set at {self.local(set_at)}.")
            return
        pin = await (self.own_pin() if self.options.own_pin else self.generated_pin())
        await self.admin.set_pin(pin)
        self.store.set_setting(PIN_SET_KEY, self.clock.now().isoformat())
        self.t.print("✓ PIN set. Signal asks for it now and then; ODIN handles that itself.")

    async def generated_pin(self) -> str:
        pin = generate_pin()
        self.t.print(
            "ODIN's PIN protects the number against being registered by someone else. Save it "
            "in the password manager now — it is shown only this once:"
        )
        self.t.print()
        self.t.print(f"    {pin}")
        self.t.print()
        while True:
            answer = await self.t.prompt("Type its last 4 characters to confirm you saved it: ")
            if answer.strip().lower() == pin[-4:]:
                return pin
            self.t.print(
                "That does not match. Check the saved entry and try again. (Lost it? Press "
                "Ctrl-C and run `odin setup` again for a new PIN.)"
            )

    async def own_pin(self) -> str:
        while True:
            pin = await self.t.secret("New PIN: ")
            if len(pin) < MIN_OWN_PIN_LENGTH:
                self.t.print(f"Use at least {MIN_OWN_PIN_LENGTH} characters.")
                continue
            if await self.t.secret("The same PIN again: ") == pin:
                return pin
            self.t.print("The two entries differ. Once more.")

    # Step 5

    async def profile(self) -> None:
        self.step(5, "Profile")
        profile = self.config.profile
        avatar = None
        if profile.avatar is not None:
            try:
                avatar = profile.avatar.read_bytes()
            except OSError as e:
                raise SetupExit(f"Cannot read the avatar {profile.avatar}: {e}") from None
        await self.admin.update_profile(profile.name, avatar, profile.about)
        self.store.set_setting(PROFILE_KEY, self.clock.now().isoformat())
        with_avatar = f" with the picture {profile.avatar.name}" if profile.avatar else ""
        self.t.print(f"✓ Profile name set to {profile.name}{with_avatar}.")
        if profile.about:
            self.t.print(f"✓ About text set to “{profile.about}”.")
        elif profile.about is not None:
            self.t.print("✓ About text cleared.")

    # Step 6

    async def hello(self) -> None:
        self.step(6, "Hello")
        operator = self.store.get_setting(OPERATOR_KEY)
        replied = self.store.get_setting(HELLO_KEY)
        if replied is not None and "hello" not in self.options.redo:
            self.t.print(f"✓ {operator} replied to ODIN at {self.local(replied)}.")
            return
        self.t.print(
            "ODIN sends you a direct message; you accept its message request and reply. That "
            "gives ODIN your profile key — without it, ODIN would only be “invited” to the "
            "groups you add it to, not a member."
        )
        operator = await self.ask_operator(operator)
        replies: asyncio.Queue[DirectMessage | None] = asyncio.Queue()
        # Listen before sending, so a quick reply cannot be missed.
        listener = asyncio.create_task(self.listen(replies))
        await asyncio.sleep(0)
        try:
            text = self.render(self.config.templates.hello)
            await self.admin.send_direct_message(operator, text)
            self.t.print(
                f"Sent to {operator}. On your phone: open the message request from "
                f"{self.config.profile.name}, accept it and reply with anything. Waiting …"
            )
            await self.wait_for_reply(operator, replies, listener)
        finally:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener
        with self.store.transaction():
            self.store.set_setting(OPERATOR_KEY, operator)
            self.store.set_setting(HELLO_KEY, self.clock.now().isoformat())
        self.t.print("✓ Got your reply.")

    async def ask_operator(self, stored: str | None) -> str:
        default = f" [{stored}]" if stored else ""
        while True:
            raw = await self.t.prompt(f"Your own Signal number, e.g. +4917…{default}: ")
            number = re.sub(r"[\s/-]", "", raw) or stored or ""
            if number == self.env.signal_number:
                self.t.print("That is ODIN's own number. Enter yours.")
            elif is_e164(number):
                return number
            else:
                self.t.print("Enter it in international format: + country code number.")

    async def listen(self, replies: asyncio.Queue[DirectMessage | None]) -> None:
        try:
            async for message in self.admin.direct_messages():
                replies.put_nowait(message)
        finally:
            replies.put_nowait(None)  # the stream ended (or failed)

    async def wait_for_reply(
        self,
        operator: str,
        replies: asyncio.Queue[DirectMessage | None],
        listener: asyncio.Task[None],
    ) -> None:
        while True:
            message = await replies.get()
            if message is None:
                await listener  # re-raises a failure
                raise SetupExit(f"The Signal API stopped delivering messages. {RUN_AGAIN}")
            if message.sender == operator:
                return
            if not message.sender.startswith("+"):
                # Signal hides the number of senders who chose so; only their UUID arrives.
                self.t.print(
                    f"Got a reply from a sender whose number is hidden ({message.sender}); "
                    "taking it as yours."
                )
                return
            self.t.print(f"(Ignoring a message from {message.sender}.)")

    # Step 7

    async def groups(self) -> None:
        self.step(7, "Groups")
        flat_env, dinner_env = self.env.flat_group_id, self.env.dinner_group_id
        if flat_env is not None and dinner_env is not None:
            self.t.print(
                "FLAT_GROUP_ID and DINNER_GROUP_ID are set; they decide the groups, so there "
                "is nothing to choose here."
            )
            return
        resolution = resolve_account(self.env, self.store)
        if resolution.account is not None and "groups" not in self.options.redo:
            for role, group in (("flat", resolution.flat), ("dinner", resolution.dinner)):
                self.t.print(f"✓ {role.capitalize()} group: {group.id} (from {group.source})")
            self.t.print("(To choose again: --redo groups.)")
            return

        self.t.print(
            "On your phone, add Odin to both groups: the flat group and the dinner group. "
            "This list updates by itself."
        )
        groups = await self.wait_for_groups()
        flat = await self.pick(groups, "flat", "the flatmates")
        dinner = await self.pick(groups, "dinner", "everyone invited", other=flat)
        with self.store.transaction():
            self.store.set_setting(FLAT_GROUP_KEY, flat.id)
            self.store.set_setting(DINNER_GROUP_KEY, dinner.id)
        self.t.print(f"✓ Flat group: {flat.name}. Dinner group: {dinner.name}.")
        for var, value in (("FLAT_GROUP_ID", flat_env), ("DINNER_GROUP_ID", dinner_env)):
            if value is not None:
                self.t.print(
                    f"Note: {var} is set ({value}) and overrides this choice while it is set."
                )

    async def wait_for_groups(self) -> list[Group]:
        shown: list[Group] | None = None
        asked: list[Group] | None = None
        while True:
            groups = sorted(await self.admin.list_groups(), key=lambda g: g.name.casefold())
            if groups != shown:
                self.show_groups(groups)
                shown = groups
            if sum(g.member for g in groups) >= 2 and groups != asked:
                asked = groups
                answer = await self.t.prompt(
                    "Are both groups listed as member? [Y = choose / n = keep waiting]: "
                )
                if answer.strip().lower() in ("", "y", "yes"):
                    return groups
            await self.sleep(GROUP_POLL_INTERVAL)

    def show_groups(self, groups: list[Group]) -> None:
        self.t.print()
        if not groups:
            self.t.print("ODIN is in no group yet. Waiting …")
            return
        self.t.print("Groups ODIN sees:")
        for number, group in enumerate(groups, start=1):
            status = "member" if group.member else "INVITED, not a member"
            self.t.print(f"  {number}. {group.name or '(no name)'} — {status}")
        invited = [g for g in groups if not g.member]
        if invited:
            names = ", ".join(g.name or "(no name)" for g in invited)
            self.t.print(
                f"ODIN is only invited to: {names}. Signal makes it a member once it has the "
                "profile key of whoever added it. Fix: that person accepts ODIN's message "
                "request and replies to it; if ODIN stays invited, remove it from the group "
                "and add it again."
            )
        if sum(g.member for g in groups) < 2:
            self.t.print("Waiting until ODIN is a member of both groups …")

    async def pick(
        self, groups: list[Group], role: str, who: str, other: Group | None = None
    ) -> Group:
        while True:
            raw = await self.t.prompt(f"Number of the {role} group ({who}): ")
            try:
                index = int(raw.strip()) - 1
            except ValueError:
                index = -1
            if not 0 <= index < len(groups):
                self.t.print(f"Enter a number from 1 to {len(groups)}.")
                continue
            group = groups[index]
            if not group.member:
                self.t.print(f"ODIN is only invited to {group.name}; fix that first (see above).")
            elif other is not None and group.id == other.id:
                self.t.print("Flat and dinner group must be different groups.")
            else:
                return group

    # Step 8

    async def test(self) -> None:
        self.step(8, "Test")
        answered = self.store.get_setting(TEST_KEY)
        if answered is not None and "test" not in self.options.redo:
            self.t.print(f"✓ Answered at {self.local(answered)}. (Again: --redo test.)")
            return
        account = resolve_account(self.env, self.store).account
        if account is None:  # cannot happen after step 7; keeps the types honest
            raise SetupExit(f"No groups chosen. {RUN_AGAIN}")
        answer = await self.t.prompt("Post a test message to the flat group now? [y/N]: ")
        if answer.strip().lower() in ("y", "yes"):
            text = self.render(self.config.templates.flat_test)
            await self.admin.send_group_message(account.flat_group_id, text)
            self.t.print("✓ Sent. Check the flat group on your phone.")
        self.store.set_setting(TEST_KEY, self.clock.now().isoformat())

    # Step 9

    def done(self) -> None:
        self.step(9, "Done")
        resolution = resolve_account(self.env, self.store)
        self.t.print(f"Number:       {self.env.signal_number}")
        self.t.print(f"Operator:     {self.store.get_setting(OPERATOR_KEY)}")
        for label, group in (
            ("Flat group:  ", resolution.flat),
            ("Dinner group:", resolution.dinner),
        ):
            self.t.print(f"{label} {group.id} (from {group.source})")
        self.t.print()
        self.t.print(
            "✓ ODIN is set up. A running `odin run` notices within 30 s and starts — no restart "
            "needed."
        )
        self.t.print(
            "Back up the signal-cli data volume now: it holds ODIN's account keys, and losing "
            "it means registering the number again (a Proxmox VM backup covers it)."
        )

    # Helpers

    def step(self, number: int, title: str) -> None:
        self.t.print()
        self.t.print(f"── Step {number}/9 · {title}")

    async def sleep(self, delay: timedelta) -> None:
        await self.clock.sleep(delay)
        # Also beat here: with a test clock, time can jump further than the heartbeat interval.
        self.store.refresh_setup_lock(self.token, self.clock.now())

    def local(self, stored: str) -> str:
        return f"{datetime.fromisoformat(stored).astimezone(self.config.timezone):%Y-%m-%d %H:%M}"

    def render(self, template: Template) -> str:
        return template.render(**self.config.placeholder_values())


# --- --status ------------------------------------------------------------------------------------


async def setup_status(
    admin: SetupSignal,
    store: Store | None,
    config: Config,
    env: Env,
    terminal: Terminal,
    clock: Clock,
) -> int:
    """Print which steps are done; returns 0 if ODIN is fully set up, else 1. Changes nothing.

    Without a store (no database yet) nothing beyond the Signal API counts as done.
    """

    def setting(key: str) -> str | None:
        return store.get_setting(key) if store is not None else None

    def local(stored: str) -> str:
        return f"{datetime.fromisoformat(stored).astimezone(config.timezone):%Y-%m-%d %H:%M}"

    rows: list[tuple[bool, str]] = []
    number = env.signal_number
    registered = False
    api_up = False
    try:
        info = await admin.about()
        if info.mode != "json-rpc":
            rows.append((False, f"Signal API: mode {info.mode!r}, needs json-rpc"))
        else:
            api_up = True
            rows.append((True, f"Signal API: {env.signal_api_url} (json-rpc, {info.version})"))
            registered = number in await admin.list_accounts()
    except (httpx.HTTPError, SignalApiError) as e:
        rows.append((False, f"Signal API: not reachable at {env.signal_api_url} ({e})"))

    if registered:
        rows.append((True, f"Registered: {number}"))
    else:
        requested = setting(CODE_REQUESTED_KEY)
        pending = f"; a code was requested at {local(requested)}" if requested else ""
        state = "unknown" if not api_up else "not registered"
        rows.append((False, f"Registered: {number} {state}{pending}"))

    for key, label in ((PIN_SET_KEY, "PIN set"), (PROFILE_KEY, "Profile applied")):
        at = setting(key)
        rows.append((at is not None, f"{label}: {local(at) if at else 'no'}"))
    replied = setting(HELLO_KEY)
    operator = setting(OPERATOR_KEY)
    rows.append(
        (
            replied is not None,
            f"Hello: reply from {operator} at {local(replied)}"
            if replied
            else "Hello: no reply from the operator yet",
        )
    )

    groups: dict[str, Group] = {}
    if registered:
        with contextlib.suppress(httpx.HTTPError, SignalApiError):
            groups = {g.id: g for g in await admin.list_groups()}
    resolution = resolve_account(env, store)
    for role, chosen in (("Flat group", resolution.flat), ("Dinner group", resolution.dinner)):
        if chosen.source is Source.UNSET or chosen.id is None:
            rows.append((False, f"{role}: not chosen"))
            continue
        line = f"{role}: {chosen.id} (from {chosen.source})"
        group = groups.get(chosen.id)
        if not registered:
            rows.append((True, line))
        elif group is None:
            rows.append((False, f"{line} — ODIN is not in this group"))
        elif not group.member:
            rows.append((False, f"{line} — {group.name}, ODIN is only invited"))
        else:
            rows.append((True, f"{line} — {group.name}"))

    for ok, line in rows:
        terminal.print(f"{'✓' if ok else '✗'} {line}")
    test = setting(TEST_KEY)
    terminal.print(f"  Test message step: {'answered at ' + local(test) if test else 'not yet'}")
    if store is not None and store.setup_lock_held(clock.now()):
        terminal.print("  `odin setup` is running right now.")
    complete = all(ok for ok, _ in rows)
    terminal.print()
    terminal.print("ODIN is set up." if complete else "Not set up yet — run: odin setup")
    return 0 if complete else 1
