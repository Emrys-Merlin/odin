"""Signal access: the client interfaces, their real and fake implementations, and parsing."""

from odin.signal.client import SignalAdmin, SignalClient
from odin.signal.errors import (
    AlreadyRegistered,
    CaptchaRequired,
    NotRegistered,
    RateLimited,
    RegistrationLocked,
    SignalApiError,
    VoiceNotYetAllowed,
    VoiceRequired,
    WrongCode,
    WrongPin,
)
from odin.signal.fake import (
    AdminCall,
    FakeSignalAdmin,
    FakeSignalClient,
    SentDirectMessage,
    SentMessage,
)
from odin.signal.models import ApiInfo, DirectMessage, Event, Group, ReactionEvent
from odin.signal.parsing import group_id_from_internal, parse_direct_message, parse_event
from odin.signal.rest import RestSignalClient

__all__ = [
    "AdminCall",
    "AlreadyRegistered",
    "ApiInfo",
    "CaptchaRequired",
    "DirectMessage",
    "Event",
    "FakeSignalAdmin",
    "FakeSignalClient",
    "Group",
    "NotRegistered",
    "RateLimited",
    "ReactionEvent",
    "RegistrationLocked",
    "RestSignalClient",
    "SentDirectMessage",
    "SentMessage",
    "SignalAdmin",
    "SignalApiError",
    "SignalClient",
    "VoiceNotYetAllowed",
    "VoiceRequired",
    "WrongCode",
    "WrongPin",
    "group_id_from_internal",
    "parse_direct_message",
    "parse_event",
]
