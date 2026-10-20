"""The anti-patterns of epic #133 as Jev questions about one unit.

Every question is asked about the state built by `audit.state`:

- `module_path`: the file the unit is in
- `module_source`: that file (outlined if it is long, see `units.module_context`)
- `target_name`: the function or method, e.g. `Engine.tick`
- `target_source`: its source

A Noul's probability, or a Score's position scaled to 0..1, is the hit strength: higher means
more likely an instance of the anti-pattern. Hits are candidates; they are verified by reading
the code before they become findings.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from units import Unit


@dataclass(frozen=True)
class Pattern:
    id: str
    title: str
    question: dict[str, Any]
    applies: Callable[[Unit], bool]


def _src(unit: Unit) -> bool:
    return not unit.is_test


def _tests(unit: Unit) -> bool:
    return unit.is_test


def _any(unit: Unit) -> bool:
    return True


def _commands(unit: Unit) -> bool:
    return unit.path.startswith("src/odin/commands/") and not unit.path.endswith("/ui.py")


def _scheduler(unit: Unit) -> bool:
    return unit.path in ("src/odin/engine.py", "src/odin/app.py")


def _noul(instructions: str, true: str, false: str) -> dict[str, Any]:
    return {
        "type": "noul",
        "instructions": instructions,
        "criteria": {"true": true, "false": false},
    }


PATTERNS = [
    Pattern(
        "P1",
        "Real clock, sleep or network outside the interfaces",
        _noul(
            "This project gets the current time only from an injected clock object and talks to "
            "Signal only through an injected client interface, so that tests can use a fixed "
            "clock and a fake client. Does the function in `target_source` itself read the real "
            "current time (for example `datetime.now()`, `time.time()`, `date.today()`, "
            "`time.monotonic()`), sleep (`time.sleep`, `asyncio.sleep`) or do network I/O "
            "(HTTP requests, sockets) directly?",
            "It directly reads the real clock, sleeps or does network I/O, and it is not itself "
            "the real implementation of the clock or Signal client interface.",
            "It takes time from an injected clock or a parameter and uses an injected client, "
            "does none of these things, or is itself the real clock or client implementation.",
        ),
        _src,
    ),
    Pattern(
        "P2",
        "Weekly-cycle message text hard-coded in code",
        _noul(
            "The messages this bot posts as part of its weekly cycle (the question to the flat "
            "group, the nudge, the announcement or cancellation to the dinner group, the tally, "
            "notices) must come from templates in the config file, not from code. Replies to "
            "chat commands are German strings in code by design and do not count, nor do log "
            "messages and exception texts. Does `target_source` contain a hard-coded text of a "
            "weekly-cycle message that is posted to a group?",
            "It builds or contains the wording of a weekly-cycle message in code.",
            "It renders config templates, or its strings are command replies, logs, errors or "
            "identifiers.",
        ),
        _src,
    ),
    Pattern(
        "P3",
        "German UI string that should live in commands/ui.py",
        _noul(
            "Chat-command replies are German strings in code. A string or phrase that several "
            "commands use belongs in the shared module `commands/ui.py`. Does `target_source` "
            "contain a German reply text that is generic rather than specific to this command "
            "(for example an error for a missing or invalid argument, a permission or "
            "confirmation message, a usage hint) and that other commands are likely to need, or "
            "already contain, in the same or nearly the same wording?",
            "It contains such a generic German text written out locally.",
            "Its texts are specific to this command, or it uses the shared texts from "
            "`commands/ui.py`.",
        ),
        _commands,
    ),
    Pattern(
        "P4",
        "Scheduler waits instead of reconciling, or a send isn't recorded",
        _noul(
            "The scheduler must be a reconcile loop: on every tick it looks at (config, state, "
            "now), does what is due and not yet recorded, and records each action after its "
            "message went out, so that nothing is sent twice and a restart resumes where it "
            "stopped. Does `target_source` break this, for example by waiting or sleeping until "
            "a specific future time, by keeping schedule progress only in memory, by sending "
            "without recording the action, or by recording it before the send?",
            "It breaks the reconcile-loop rule in one of these ways.",
            "It follows the rule, or is unrelated to sending and recording actions.",
        ),
        _scheduler,
    ),
    Pattern(
        "P5",
        "Test touches real time, network or files outside tmp_path",
        _noul(
            "Tests in this project must not touch the real time or the network: they use a "
            "fixed clock and a fake Signal client. Files may only be written below pytest's "
            "temporary directory (`tmp_path`, `tmp_path_factory`); reading files that are "
            "committed to the repository is fine. Does the test or helper in `target_source` "
            "read the real clock, sleep for real, open network connections, or write files "
            "outside a temporary directory?",
            "It does at least one of these.",
            "It uses the fixed clock, the fake client and temporary directories only.",
        ),
        _tests,
    ),
    Pattern(
        "G1",
        "Docstring or comment contradicts the code",
        _noul(
            "Does a docstring or comment in `target_source` state something that the code "
            "does not do: a wrong return value or condition, a described behaviour that is "
            "missing, a stale parameter or step, or a claim the code contradicts?",
            "At least one docstring or comment is contradicted by the code.",
            "The docstrings and comments match the code, or there are none.",
        ),
        _any,
    ),
    Pattern(
        "G2",
        "Misleading name",
        _noul(
            "Is the name `target_name`, or the name of a parameter or local variable in "
            "`target_source`, misleading: a reader who goes by the name would expect clearly "
            "different behaviour or contents than the code has?",
            "A name clearly misrepresents what the code does or holds.",
            "The names are accurate, even if short.",
        ),
        _any,
    ),
    Pattern(
        "G3",
        "Function with several unrelated responsibilities",
        {
            "type": "score",
            "instructions": "How many unrelated responsibilities does the function in "
            "`target_source` have?",
            "criteria": [
                "One clear job, possibly done in a few steps",
                "One main job plus a small unrelated side task",
                "Two distinct jobs that would read better as separate functions",
                "Several unrelated jobs mixed together",
            ],
        },
        _src,
    ),
    Pattern(
        "G4",
        "Error swallowed in a way that hides failures",
        _noul(
            "Does `target_source` catch an exception and then hide a real failure: for example "
            "`except Exception: pass`, returning a default value without logging, or catching "
            "much more broadly than the errors it expects to handle?",
            "A failure can be silently swallowed.",
            "There is no exception handling, or the handler logs, re-raises, reports the error "
            "or narrowly handles an expected case.",
        ),
        _src,
    ),
    Pattern(
        "G5",
        "Stringly-typed code",
        _noul(
            "Does `target_source` pass around or branch on raw strings or dicts from a fixed, "
            "known set (for example comparing a `kind` string against literals, or building "
            "dicts with fixed keys) where an Enum, a Literal type or a dataclass would make the "
            "code safer?",
            "It uses raw strings or dicts for a closed set of values or a fixed record shape.",
            "It uses typed structures, or the strings and dicts are genuinely open-ended, such as "
            "user text, template text or JSON at an API boundary.",
        ),
        _src,
    ),
    Pattern(
        "G6",
        "Boolean flag parameter switching behaviour",
        _noul(
            "Does the function in `target_source` take a boolean parameter that switches it "
            "between two substantially different behaviours, so that two functions or an "
            "explicit option type would be clearer for its callers?",
            "A boolean parameter selects between two substantially different code paths.",
            "It has no boolean parameter, or its booleans only adjust a detail.",
        ),
        _src,
    ),
    Pattern(
        "G7",
        "Hidden mutable module-level state",
        _noul(
            "Does `target_source` read or modify mutable module-level state: a global variable "
            "that is reassigned (`global` statement) or a module-level list, dict, set or object "
            "that is changed at runtime, so that its behaviour depends on hidden state rather "
            "than its arguments?",
            "It reads or changes module-level state that is mutated at runtime.",
            "It only uses arguments, attributes of its own objects and constants that are never "
            "changed.",
        ),
        _src,
    ),
    Pattern(
        "G8",
        "Unnamed magic number or string with domain meaning",
        _noul(
            "Does `target_source` contain a literal number or string with a domain meaning (a "
            "timeout, a limit, a weekday index, a status keyword, a port) that is used without a "
            "named constant or an explanation, so its meaning is unclear to a reader?",
            "It contains such an unexplained literal.",
            "Its literals are obvious (0, 1, empty strings), named, explained, "
            "or user-facing text.",
        ),
        _src,
    ),
    Pattern(
        "D2",
        "Repeated test setup that should be a fixture",
        _noul(
            "Does `target_source` repeat a block of setup code (building a config, a store, a "
            "fake client, a clock or test data) that other tests in `module_source` repeat almost "
            "identically, so that a shared fixture or helper would be clearer?",
            "It contains several lines of setup that are copied in other tests of the module.",
            "Its setup is specific to this test, short, or already uses fixtures or helpers.",
        ),
        _tests,
    ),
    Pattern(
        "T1",
        "Test without a meaningful assertion",
        _noul(
            "Is `target_name` a test function whose checks could not fail for a plausible bug: "
            "it has no assertion at all, only checks that a result is not None or truthy, or "
            "asserts something that is true by construction? `pytest.raises` and assertions in "
            "helpers it calls count as checks.",
            "It is a test, and its checks could not catch a plausible bug.",
            "It is not a test function (a fixture or helper), or it checks results that a bug "
            "would change.",
        ),
        _tests,
    ),
    Pattern(
        "T2",
        "Test checks implementation details",
        _noul(
            "Does the test in `target_source` check implementation details instead of "
            "observable behaviour: patching or mocking internal functions of the code under "
            "test, or asserting on private attributes or on calls between internal functions, "
            "so that a correct refactoring would break it? Using the project's fakes (fake "
            "Signal client, fixed clock, temporary store) and checking what they recorded is "
            "observable behaviour.",
            "It depends on internals that a correct refactoring could change.",
            "It only checks inputs, outputs, stored state and what the fakes recorded, or it is "
            "not a test function.",
        ),
        _tests,
    ),
    Pattern(
        "T3",
        "Test name doesn't match what it checks",
        _noul(
            "Is `target_name` a test function whose name (and docstring, if any) describes "
            "something clearly different from what `target_source` sets up and checks?",
            "The name or docstring promises a different scenario or result than the test checks.",
            "The name matches what the test checks, or it is not a test function.",
        ),
        _tests,
    ),
]

BY_ID = {p.id: p for p in PATTERNS}


def strength(answer: dict[str, Any]) -> float:
    """Hit strength in 0..1 of a Noul or Score answer."""
    if answer["type"] == "noul":
        return answer["noul"]
    levels = len(answer["legend"]) - 1
    return sum(int(k) * p for k, p in answer["probabilities"].items()) / levels
