"""Signal access: the client interfaces, their real and fake implementations, and parsing."""

from odib.signal.client import SignalAdmin, SignalClient
from odib.signal.errors import (
    AlreadyRegistered,
    CaptchaRequired,
    NotRegistered,
    RateLimited,
    RegistrationLocked,
    SignalApiError,
    VoiceNotYetAllowed,
    VoiceRequired,
    WrongCode,
)
from odib.signal.fake import (
    AdminCall,
    FakeSignalAdmin,
    FakeSignalClient,
    SentDirectMessage,
    SentMessage,
)
from odib.signal.models import ApiInfo, DirectMessage, Event, Group, ReactionEvent
from odib.signal.parsing import group_id_from_internal, parse_direct_message, parse_event
from odib.signal.rest import RestSignalClient

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
    "group_id_from_internal",
    "parse_direct_message",
    "parse_event",
]
