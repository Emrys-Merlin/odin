"""Plant known anti-patterns into a copy of the repository, for epic #133.

    uv run scripts/quality/plant.py

Copies src/ and tests/ to out/planted/ and appends one function per planted defect to a
module. out/planted/plants.json lists them (unit key and pattern ID), so the audit's recall can
be measured: `audit.py run --root scripts/quality/out/planted --out .../planted.jsonl`.

The planted code is never run, only read; it parses but need not import.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from jev import OUT

REPO = Path(__file__).resolve().parents[2]
PLANTED = OUT / "planted"

# (pattern ID, module, function name, code appended to the module)
PLANTS = [
    (
        "P1",
        "src/odin/engine.py",
        "_week_has_started",
        '''
def _week_has_started(config: Config, week: date) -> bool:
    """Whether the flat ask of `week` is already due."""
    now = datetime.now(UTC)
    return now >= config.when(config.schedule.flat_ask, week).astimezone(UTC)
''',
    ),
    (
        "P2",
        "src/odin/engine.py",
        "_cancellation_text",
        '''
def _cancellation_text(week: date) -> str:
    """The message to the dinner group when nobody confirmed."""
    return (
        f"Am {week:%d.%m.} fällt das Essen leider aus.\\n\\n"
        f"Sorry, no dinner on {week:%d %B} this week."
    )
''',
    ),
    (
        "P3",
        "src/odin/commands/skip.py",
        "_reply_failed",
        '''
def _reply_failed() -> str:
    """Reply when the skip could not be stored."""
    return "Da ist etwas schiefgegangen – bitte später nochmal versuchen."
''',
    ),
    (
        "P4",
        "src/odin/app.py",
        "_wait_for_next_action",
        '''
async def _wait_for_next_action(config: Config, clock: Clock) -> None:
    """Sleep until the next scheduled action of the week is due."""
    now = clock.now()
    upcoming = upcoming_actions(config, now)
    if upcoming:
        await asyncio.sleep((upcoming[0].at - now).total_seconds())
''',
    ),
    (
        "P5",
        "tests/test_store.py",
        "test_store_survives_reopen",
        """
def test_store_survives_reopen() -> None:
    path = Path("odin-test.db")
    with Store.open(path) as store:
        store.record_action(date.today(), Action.FLAT_ASK, datetime.now(UTC))
    with Store.open(path) as store:
        assert store.action_outcome(date.today(), Action.FLAT_ASK) is Outcome.SENT
""",
    ),
    (
        "G1",
        "src/odin/store.py",
        "_earliest",
        '''
def _earliest(moments: list[datetime]) -> datetime | None:
    """The earliest of `moments`, or None if there are none."""
    return max(moments) if moments else None
''',
    ),
    (
        "G2",
        "src/odin/overrides.py",
        "is_valid_override",
        '''
def is_valid_override(store: Store, key: str, value: str, now: datetime) -> bool:
    """Store an override for `key`."""
    store.set_override(key, value, "chat", now)
    store.delete_pending_dinner()
    return True
''',
    ),
    (
        "G3",
        "src/odin/commands/settext.py",
        "_handle_and_report",
        '''
def _handle_and_report(store: Store, config: Config, args: str, sender: str, now: datetime) -> str:
    """Set a template from chat."""
    name, _, text = args.partition(" ")
    if name not in EDITABLE_TEMPLATES:
        return "Unbekannte Vorlage."
    store.set_override(template_key(name), text, sender, now)
    logger.info("template %s changed by %s", name, sender)
    lines = [line for line in Path("odin.log").read_text().splitlines() if "ERROR" in line]
    stats = {"changes": len(store.overrides()), "errors": len(lines)}
    Path("stats.json").write_text(json.dumps(stats))
    week = dinner_week(config, now)
    return f"Gespeichert. Nächste Woche: {week:%d.%m.}"
''',
    ),
    (
        "G4",
        "src/odin/signal/rest.py",
        "_group_name",
        '''
async def _group_name(client: RestSignalClient, group_id: str) -> str:
    """The display name of a group."""
    try:
        groups = await client.list_groups()
        return next(g.name for g in groups if g.id == group_id)
    except Exception:
        return ""
''',
    ),
    (
        "G5",
        "src/odin/commands/status.py",
        "_state_line",
        '''
def _state_line(step: dict[str, str]) -> str:
    """One line of the status reply for a step."""
    if step["state"] == "sent":
        return f"✅ {step['name']}"
    if step["state"] == "skipped":
        return f"⏭️ {step['name']}"
    if step["state"] == "failed":
        return f"❌ {step['name']}"
    return f"⏳ {step['name']}"
''',
    ),
    (
        "G6",
        "src/odin/commands/preview.py",
        "_render",
        '''
def _render(config: Config, name: str, week: date, for_chat: bool) -> str:
    """A template rendered for `week`."""
    if for_chat:
        values = placeholder_values(config, week)
        return getattr(config.templates, name).format(**values)
    path = Path(f"/tmp/preview-{name}.html")
    path.write_text(f"<pre>{getattr(config.templates, name)}</pre>")
    return str(path)
''',
    ),
    (
        "G7",
        "src/odin/reactions.py",
        "_remember_reaction",
        '''
_SEEN: dict[str, int] = {}


def _remember_reaction(sender: str) -> bool:
    """Whether `sender` reacted before; counts the reaction."""
    _SEEN[sender] = _SEEN.get(sender, 0) + 1
    return _SEEN[sender] > 1
''',
    ),
    (
        "G8",
        "src/odin/events.py",
        "_stale",
        '''
def _stale(event_time: datetime, now: datetime) -> bool:
    """Whether an event is too old to act on."""
    return (now - event_time).total_seconds() > 5400
''',
    ),
    (
        "T1",
        "tests/test_engine.py",
        "test_reconcile_on_dinner_day",
        """
def test_reconcile_on_dinner_day(bot: Bot) -> None:
    bot.run(local(11, 18))
    bot.run(local(11, 19))
    assert bot is not None
""",
    ),
    (
        "T2",
        "tests/test_engine.py",
        "test_decision_uses_confirmations",
        """
def test_decision_uses_confirmations(bot: Bot, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr("odin.engine._Week._confirmations", lambda self: calls.append(1) or 1)
    bot.run(local(8, 18))
    assert calls == [1]
""",
    ),
    (
        "T3",
        "tests/test_engine.py",
        "test_announcement_is_sent_after_a_confirmation",
        """
def test_announcement_is_sent_after_a_confirmation(bot: Bot) -> None:
    bot.run(local(6, 18))
    bot.run(local(8, 18))
    assert bot.outcome(Action.CANCELLATION) is Outcome.SENT
    assert bot.outcome(Action.ANNOUNCEMENT) is None
""",
    ),
]

# Duplicates of existing functions, for the D1 experiment: (original unit key, module, function
# name, code). The first is a renamed copy, the others rewrite the same logic.
DUPLICATES = [
    (
        "src/odin/engine.py::dinner_week",
        "src/odin/commands/status.py",
        "_week_of",
        '''
def _week_of(cfg: Config, moment: datetime) -> date:
    """Which dinner week `moment` falls into, by its dinner date."""
    moment = moment.astimezone(UTC)
    here = moment.astimezone(cfg.timezone)
    point = cfg.schedule.dinner
    day = here.date() + timedelta(days=(point.weekday - here.weekday()) % 7)
    if moment >= cfg.when(point, day).astimezone(UTC):
        day += timedelta(days=7)
    return day
''',
    ),
    (
        "src/odin/commands/ui.py::short_date",
        "src/odin/commands/schedule.py",
        "_day_label",
        '''
def _day_label(day: date) -> str:
    """Label for a day in the schedule reply."""
    names = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    return names[day.weekday()] + " " + day.strftime("%d.%m.%Y")
''',
    ),
    (
        "src/odin/config.py::is_e164",
        "src/odin/setup.py",
        "_looks_like_phone_number",
        '''
def _looks_like_phone_number(text: str) -> bool:
    """Whether `text` can be used as the bot's number."""
    if not text.startswith("+") or not text[1:].isdigit():
        return False
    return text[1] != "0" and 7 <= len(text) - 1 <= 15
''',
    ),
]


def main() -> None:
    if PLANTED.exists():
        shutil.rmtree(PLANTED)
    for part in ("src", "tests"):
        shutil.copytree(REPO / part, PLANTED / part)
    truth = []
    for pattern, module, name, code in PLANTS:
        with (PLANTED / module).open("a") as f:
            f.write("\n" + code)
        truth.append({"pattern": pattern, "key": f"{module}::{name}"})
    for original, module, name, code in DUPLICATES:
        with (PLANTED / module).open("a") as f:
            f.write("\n" + code)
        truth.append({"pattern": "D1", "key": f"{module}::{name}", "original": original})
    (PLANTED / "plants.json").write_text(json.dumps(truth, indent=2))
    print(f"planted {len(truth)} defects in {PLANTED}")


if __name__ == "__main__":
    main()
