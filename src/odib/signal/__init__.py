"""Signal access: the client interface, its real and fake implementations, and parsing."""

from odib.signal.client import SignalClient
from odib.signal.fake import FakeSignalClient, SentMessage
from odib.signal.models import Event, Group, ReactionEvent
from odib.signal.parsing import group_id_from_internal, parse_event
from odib.signal.rest import RestSignalClient

__all__ = [
    "Event",
    "FakeSignalClient",
    "Group",
    "ReactionEvent",
    "RestSignalClient",
    "SentMessage",
    "SignalClient",
    "group_id_from_internal",
    "parse_event",
]
