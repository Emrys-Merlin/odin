"""The names of the weekly cycle: the points of its schedule and its steps.

Both are `StrEnum`s, so a member is its plain string wherever it leaves the code (config keys,
override keys, chat arguments, log lines). No imports from `odin`, so every module can use them.
"""

from enum import StrEnum


class SchedulePoint(StrEnum):
    """A point of the weekly schedule, in schedule order.

    The value is the point's name everywhere outside the code: the key in the TOML
    (``[schedule.<point>]``), in overrides (``schedule.<point>``) and in chat commands.
    """

    FLAT_ASK = "flat_ask"
    NUDGE = "nudge"
    FLAT_DEADLINE = "flat_deadline"
    RSVP_BY = "rsvp_by"
    TALLY = "tally"
    COOK = "cook"
    DINNER = "dinner"

    @property
    def attr(self) -> str:
        """The `Schedule` field that holds the point's time."""
        return "nudge_time" if self is SchedulePoint.NUDGE else self.value


class StepName(StrEnum):
    """A step of the weekly cycle, in schedule order."""

    FLAT_ASK = "flat_ask"
    NUDGE = "nudge"
    DECISION = "decision"  # announcement or cancellation
    TALLY = "tally"

    @property
    def label(self) -> str:
        """The step in `odin check-config`'s list of upcoming actions."""
        return _STEP_LABELS[self]


_STEP_LABELS = {
    StepName.FLAT_ASK: "flat ask",
    StepName.NUDGE: "nudge",
    StepName.DECISION: "announcement / cancellation",
    StepName.TALLY: "tally",
}
