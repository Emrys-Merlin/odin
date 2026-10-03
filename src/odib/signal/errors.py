"""Map signal-cli-rest-api error responses to typed exceptions. The one place that knows them.

signal-cli-rest-api answers every failed call with HTTP 400 and ``{"error": "<message>"}`` —
rate limits included — so the cause is told apart by substrings of the message, which come
from signal-cli or from the REST API itself. A 429 is treated as a rate limit as well.

Every exception keeps the original message so it can be shown to the operator as is (e.g. the
rate limit's "next attempt" time).
"""

import json
import re

import httpx


class SignalApiError(Exception):
    """A Signal API call failed. ``message`` is the API's error text, unchanged."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class CaptchaRequired(SignalApiError):
    """Registration needs a (new) captcha: none was given, or it was invalid or expired."""


class VoiceRequired(SignalApiError):
    """SMS verification is not possible for this number; wait 60 s, then register by voice."""


class VoiceNotYetAllowed(SignalApiError):
    """Voice verification was requested before an SMS was requested and a minute had passed."""


class RateLimited(SignalApiError):
    """Signal rate-limited the request. ``next_attempt`` is when to retry, if Signal said."""

    @property
    def next_attempt(self) -> str | None:
        match = re.search(r"Next attempt may be tried at ([^\n(]+)", self.message)
        return match.group(1).strip() if match else None


class RegistrationLocked(SignalApiError):
    """The number has a registration lock (PIN); ``hours_remaining`` until it resets."""

    @property
    def hours_remaining(self) -> int | None:
        match = re.search(r"Hours remaining until reset: (\d+)", self.message)
        return int(match.group(1)) if match else None


class WrongCode(SignalApiError):
    """Verification failed, e.g. the code is wrong or expired."""


class AlreadyRegistered(SignalApiError):
    """The account is already registered; signal-cli-rest-api cannot re-register it."""


class NotRegistered(SignalApiError):
    """The account does not exist (not registered or not verified yet)."""


# Checked in order; the first matching pattern wins.
_PATTERNS: list[tuple[re.Pattern[str], type[SignalApiError]]] = [
    (re.compile(r"Rate limit reached"), RateLimited),
    (re.compile(r"Captcha required for verification|Invalid captcha given\."), CaptchaRequired),
    (re.compile(r"Couldn't use SMS verification to register"), VoiceRequired),
    (
        re.compile(r"Before requesting voice verification you need to request SMS"),
        VoiceNotYetAllowed,
    ),
    (re.compile(r"This number is locked with a pin"), RegistrationLocked),
    (re.compile(r"Verify error:"), WrongCode),
    (re.compile(r"Account is already registered"), AlreadyRegistered),
    (re.compile(r"Specified account does not exist|User .* is not registered"), NotRegistered),
]


def error_from_response(status: int, body: str) -> SignalApiError:
    """Build the exception for a failed response with ``status`` and raw ``body``."""
    message = _message(body)
    for pattern, error_type in _PATTERNS:
        if pattern.search(message):
            return error_type(status, message)
    if status == 429:
        return RateLimited(status, message)
    return SignalApiError(status, message)


def raise_for_api_error(response: httpx.Response) -> None:
    """Raise the matching :class:`SignalApiError` if ``response`` is not a success."""
    if not response.is_success:
        raise error_from_response(response.status_code, response.text)


def _message(body: str) -> str:
    """The ``error`` field of a JSON body, else the body itself."""
    try:
        data = json.loads(body)
    except ValueError:
        return body.strip()
    if isinstance(data, dict) and isinstance(data.get("error"), str):
        return data["error"]
    return body.strip()
