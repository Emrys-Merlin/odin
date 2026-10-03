"""Operator I/O for `odib setup`: a console implementation and a scripted one for tests."""

import asyncio
import getpass
import sys
import threading
from collections import deque
from collections.abc import Callable, Iterable
from typing import Protocol


class Terminal(Protocol):
    """Prints lines and reads answers. Reading raises ``EOFError`` when input has ended."""

    def print(self, text: str = "") -> None: ...

    async def prompt(self, question: str) -> str:
        """Ask ``question`` and return the answer (without the newline)."""
        ...

    async def secret(self, question: str) -> str:
        """Like ``prompt``, but the answer is not echoed."""
        ...


class ConsoleTerminal:
    """stdin/stdout. Input is read in a daemon thread, so the event loop keeps running (the
    setup lock's heartbeat) and Ctrl-C is not held up by a blocked read."""

    def print(self, text: str = "") -> None:
        print(text, flush=True)

    async def prompt(self, question: str) -> str:
        return await _in_thread(lambda: input(question))

    async def secret(self, question: str) -> str:
        return await _in_thread(lambda: getpass.getpass(question, stream=sys.stdout))


async def _in_thread(read: Callable[[], str]) -> str:
    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()

    def resolve(result: str | None, error: BaseException | None) -> None:
        if future.done():
            return  # the wizard was cancelled meanwhile
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result or "")

    def target() -> None:
        try:
            result = read()
        except BaseException as e:  # EOFError above all; handed to the waiting coroutine
            loop.call_soon_threadsafe(resolve, None, e)
        else:
            loop.call_soon_threadsafe(resolve, result, None)

    # A daemon thread rather than asyncio.to_thread: a read blocked at exit must not keep the
    # process alive.
    threading.Thread(target=target, daemon=True).start()
    return await future


class ScriptedTerminal:
    """Answers prompts from a script and records everything that was shown.

    ``output`` holds every printed line and every question. Once the script is used up, the
    next prompt raises ``EOFError``, like a console whose input was closed.
    """

    def __init__(self, answers: Iterable[str] = ()) -> None:
        self.answers = deque(answers)
        self.output: list[str] = []
        self.secrets_asked = 0

    @property
    def text(self) -> str:
        return "\n".join(self.output)

    def print(self, text: str = "") -> None:
        self.output.append(text)

    async def prompt(self, question: str) -> str:
        self.output.append(question)
        await asyncio.sleep(0)
        if not self.answers:
            raise EOFError
        return self.answers.popleft()

    async def secret(self, question: str) -> str:
        self.secrets_asked += 1
        return await self.prompt(question)
