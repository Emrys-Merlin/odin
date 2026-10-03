import json
from pathlib import Path

import httpx
import pytest

from odib.signal import (
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
from odib.signal.errors import error_from_response, raise_for_api_error

FIXTURES = Path(__file__).parent / "fixtures" / "signal"
CASES = {case["case"]: case for case in json.loads((FIXTURES / "errors.json").read_text())}


def error(case: str) -> SignalApiError:
    data = CASES[case]
    body = data["body"]
    return error_from_response(data["status"], body if isinstance(body, str) else json.dumps(body))


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("captcha_required", CaptchaRequired),
        ("captcha_invalid", CaptchaRequired),
        ("voice_required", VoiceRequired),
        ("voice_not_yet_allowed", VoiceNotYetAllowed),
        ("rate_limited", RateLimited),
        ("rate_limited_next_attempt", RateLimited),
        ("rate_limited_429", RateLimited),
        ("registration_locked", RegistrationLocked),
        ("wrong_code", WrongCode),
        ("already_registered", AlreadyRegistered),
        ("not_registered_jsonrpc", NotRegistered),
        ("not_registered_normal", NotRegistered),
    ],
)
def test_maps_message_to_exception(case: str, expected: type[SignalApiError]) -> None:
    exc = error(case)
    assert type(exc) is expected
    assert exc.status == CASES[case]["status"]
    assert exc.message == CASES[case]["body"]["error"]
    assert str(exc) == exc.message


def test_every_fixture_case_is_tested() -> None:
    assert set(CASES) == {
        "captcha_required",
        "captcha_invalid",
        "voice_required",
        "voice_not_yet_allowed",
        "rate_limited",
        "rate_limited_next_attempt",
        "rate_limited_429",
        "registration_locked",
        "wrong_code",
        "already_registered",
        "not_registered_jsonrpc",
        "not_registered_normal",
        "generic",
        "generic_not_json",
    }


def test_generic_error_keeps_status_and_message() -> None:
    exc = error("generic")
    assert type(exc) is SignalApiError
    assert (exc.status, exc.message) == (400, "Failed to update profile: something unexpected")


def test_generic_error_with_non_json_body() -> None:
    exc = error("generic_not_json")
    assert type(exc) is SignalApiError
    assert (exc.status, exc.message) == (502, "Bad Gateway")


def test_rate_limit_next_attempt() -> None:
    exc = error("rate_limited_next_attempt")
    assert isinstance(exc, RateLimited)
    assert exc.next_attempt == "2026-10-03T20:15:00Z"
    assert "Next attempt may be tried at" in exc.message


def test_rate_limit_without_next_attempt() -> None:
    exc = error("rate_limited")
    assert isinstance(exc, RateLimited)
    assert exc.next_attempt is None


def test_registration_lock_hours_remaining() -> None:
    exc = error("registration_locked")
    assert isinstance(exc, RegistrationLocked)
    assert exc.hours_remaining == 167


def test_all_errors_are_signal_api_errors() -> None:
    for case in CASES:
        assert isinstance(error(case), SignalApiError)


def test_raise_for_api_error() -> None:
    raise_for_api_error(httpx.Response(201))
    raise_for_api_error(httpx.Response(204))
    with pytest.raises(AlreadyRegistered):
        raise_for_api_error(httpx.Response(400, json={"error": "Account is already registered"}))
