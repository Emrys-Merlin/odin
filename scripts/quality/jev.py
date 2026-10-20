"""Minimal Jev client for the code-quality audit, epic #133.

Calls TypeSafe's Jev through OpenRouter's Decisions API with the standard library only, so the
audit adds no dependency. Set OPENROUTER_API_KEY; in a Claude Code cloud session the proxy
injects the key and the variable can stay unset.

Responses are cached in out/cache/ by a hash of the request, so a rerun costs nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.14"
OUT = Path(__file__).resolve().parent / "out"
CACHE = OUT / "cache"

# Above about 32 KB of text, Jev switches to its slower, less accurate long-context mode.
LONG_CONTEXT_BYTES = 32_000

type Request = tuple[dict[str, Any], dict[str, Any]]


def ask(state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
    """Answer `questions` about `state`; returns the full response (answers, usage, model)."""
    body = json.dumps(
        {"model": MODEL, "state": state, "questions": questions}, sort_keys=True
    ).encode()
    cached = CACHE / f"{hashlib.sha256(body).hexdigest()}.json"
    if cached.exists():
        return json.loads(cached.read_text())
    headers = {"Content-Type": "application/json"}
    if key := os.environ.get("OPENROUTER_API_KEY"):
        headers["Authorization"] = f"Bearer {key}"
    for attempt in range(5):
        try:
            request = urllib.request.Request(URL, data=body, headers=headers)
            with urllib.request.urlopen(request, timeout=300) as response:
                result = json.load(response)
            break
        except urllib.error.HTTPError as error:
            if (error.code < 500 and error.code != 429) or attempt == 4:
                raise RuntimeError(f"Jev {error.code}: {error.read()[:500]!r}") from error
        except urllib.error.URLError, TimeoutError:
            if attempt == 4:
                raise
        time.sleep(2**attempt)
    result["long_context"] = len(json.dumps(state)) > LONG_CONTEXT_BYTES
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(result))
    return result


def ask_many(requests: Iterable[Request], workers: int = 8) -> list[dict[str, Any]]:
    """`ask` for each (state, questions) pair, in parallel, in input order."""
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(lambda r: ask(*r), requests))


def cost(responses: Iterable[dict[str, Any]]) -> float:
    """Total cost in USD as OpenRouter reports it."""
    return sum(r["usage"]["cost"] for r in responses)
